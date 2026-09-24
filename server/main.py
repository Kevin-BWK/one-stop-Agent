"""FastAPI 入口：把 AgentService 暴露为 HTTP 接口。

运行（在项目根目录）：
    pip install -r requirements.txt
    uvicorn server.main:app --reload
"""
import asyncio
import json

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from app.orchestrator.preview import build_preview

from .materials import build_router
from .schemas import (ApplyRequest, AskRequest, FieldSubmitRequest,
                      MessageRequest, PreviewRequest, SessionCreateRequest)
from .service import AgentService
from .stream import (answer_question, iter_events, load_case, load_intake,
                     load_scenario, material_gate, missing_required, sse_stream)


def create_app() -> FastAPI:
    app = FastAPI(title="one-stop-agent API", version="0.1.0")
    service = AgentService()
    app.state.service = service
    app.include_router(build_router())

    def intake_or_400(intake_id):
        """受理前置校验：材料没交齐就不允许开始办理。"""
        if not intake_id:
            return None
        intake = load_intake(intake_id)
        if intake is None:
            raise HTTPException(status_code=404, detail="材料受理号不存在：" + intake_id)
        return intake

    def intake_guard(scenario, intake):
        blocked = material_gate(scenario, intake)
        if blocked:
            raise HTTPException(status_code=400,
                                detail="这些材料还没交齐或还没通过核验：" + "、".join(blocked))

    def attach_hook(session_id):
        """多轮会话路径：编排结束后把办理单挂回 session，供会话内查询进度。"""
        if not session_id:
            return None
        return lambda case: service.attach_case(session_id, case)


    @app.get("/health")
    def health():
        return {"status": "ok", "moma": service.moma.mode()}

    @app.post("/api/session")
    def create_session(req: SessionCreateRequest):
        try:
            return service.create_session(req.scenario_id)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @app.post("/api/chat")
    def chat(req: MessageRequest):
        try:
            return service.handle_message(req.session_id, req.message)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @app.post("/api/fields")
    def submit_field(req: FieldSubmitRequest):
        try:
            return service.submit_field(req.session_id, req.key, req.value)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/cases/{case_id}")
    def get_case(case_id: str):
        # 事件流办理单落盘在 data/runtime/cases.json；多轮会话办理单在 service 内存里
        case = load_case(case_id)
        if case is None:
            case = service.get_case(case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="办理单不存在")
        return case

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str):
        try:
            return service.get_session(session_id)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))

    # ---------- 前端事件流（一次性提交并开始办理）----------
    # App（成品端）：WebSocket；H5（调试端）：SSE。两端事件负载格式一致。

    @app.get("/scenarios/{scenario_id}")
    def get_scenario(scenario_id: str):
        scenario = load_scenario(scenario_id)
        if scenario is None:
            raise HTTPException(status_code=404, detail="场景不存在")
        return scenario

    @app.post("/api/preview")
    def preview(req: PreviewRequest):
        """条件判定实时预判：按当前（可能还不完整的）表单预估事项与材料。

        只读、无状态：不建材料收集单、不落库，纯函数求值，可任意频率调用。
        """
        scenario = load_scenario(req.scenario_id)
        if scenario is None:
            raise HTTPException(status_code=404, detail="场景不存在")
        return build_preview(scenario, req.answers)

    @app.post("/api/ask")
    def ask(req: AskRequest):
        """对话区提问：返回自然语言回答（咨询意图）。

        带 `session_id` 时复用该会话的上下文 → **多轮上下文**（见 `docs/08`），
        用户才能问"那第二个呢"这种省略句；不带时等价于无状态单轮问答。
        """
        scenario = load_scenario(req.scenario_id)
        if scenario is None:
            raise HTTPException(status_code=404, detail="场景不存在")
        question = (req.question or "").strip()
        if not question:
            raise HTTPException(status_code=400, detail="问题不能为空")
        context = None
        if req.session_id:
            try:
                context = service.context_of(req.session_id)
            except KeyError as e:
                raise HTTPException(status_code=404, detail=str(e))
        return {"question": question, "answer": answer_question(scenario, question, context)}

    @app.get("/apply")
    def apply_stream(scenario_id: str, utterance: str = "", answers: str = "{}",
                     intake_id: str = "", session_id: str = ""):
        """H5 端 SSE：`EventSource` 只能发 GET，故参数走查询串。"""
        scenario = load_scenario(scenario_id)
        if scenario is None:
            raise HTTPException(status_code=404, detail="场景不存在")
        try:
            parsed = json.loads(answers or "{}")
        except ValueError:
            raise HTTPException(status_code=400, detail="answers 不是合法 JSON")
        missing = missing_required(scenario, parsed)
        if missing:
            raise HTTPException(status_code=400, detail="还缺这些必填信息：" + "、".join(missing))
        intake = intake_or_400(intake_id)
        intake_guard(scenario, intake)
        return StreamingResponse(
            sse_stream(scenario, utterance, parsed, intake, attach_hook(session_id)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/apply")
    def apply_stream_post(req: ApplyRequest):
        """与 GET 等价的 POST 形态（供 fetch 流式客户端使用）。"""
        scenario = load_scenario(req.scenario_id)
        if scenario is None:
            raise HTTPException(status_code=404, detail="场景不存在")
        missing = missing_required(scenario, req.answers)
        if missing:
            raise HTTPException(status_code=400, detail="还缺这些必填信息：" + "、".join(missing))
        intake = intake_or_400(req.intake_id)
        intake_guard(scenario, intake)
        return StreamingResponse(
            sse_stream(scenario, req.utterance, req.answers, intake, attach_hook(req.session_id)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.websocket("/ws/apply")
    async def apply_socket(websocket: WebSocket):
        """App 端 WebSocket：先收一次性提交参数，再持续推送事件。"""
        await websocket.accept()
        try:
            payload = await websocket.receive_json()
        except (ValueError, WebSocketDisconnect):
            payload = {}
        scenario = load_scenario(payload.get("scenario_id", ""))
        if scenario is None:
            await websocket.send_json({"type": "error", "data": {"code": "NotFound", "message": "场景不存在"}})
            await websocket.close()
            return

        try:
            intake = intake_or_400(payload.get("intake_id", ""))
            intake_guard(scenario, intake)
        except HTTPException as exc:
            await websocket.send_json(
                {"type": "error", "data": {"code": "BadRequest", "message": str(exc.detail)}})
            await websocket.close()
            return

        loop = asyncio.get_running_loop()
        hook = attach_hook(payload.get("session_id", ""))

        def pump():
            for event in iter_events(scenario, payload.get("utterance", ""),
                                     payload.get("answers") or {}, intake, hook):
                asyncio.run_coroutine_threadsafe(websocket.send_json(event.to_dict()), loop).result()

        try:
            await loop.run_in_executor(None, pump)
        except WebSocketDisconnect:
            return
        finally:
            try:
                await websocket.close()
            except RuntimeError:
                pass

    return app


app = create_app()