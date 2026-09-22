"""FastAPI 入口：把 AgentService 暴露为 HTTP 接口。

运行（在项目根目录）：
    pip install -r requirements.txt
    uvicorn server.main:app --reload
"""
import asyncio
import json

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from .schemas import (ApplyRequest, FieldSubmitRequest, MessageRequest,
                      SessionCreateRequest)
from .service import AgentService
from .stream import iter_events, load_case, load_scenario, sse_stream


def create_app() -> FastAPI:
    app = FastAPI(title="one-stop-agent API", version="0.1.0")
    service = AgentService()
    app.state.service = service

    @app.get("/health")
    def health():
        return {"status": "ok"}

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

    @app.get("/apply")
    def apply_stream(scenario_id: str, utterance: str = "", answers: str = "{}"):
        """H5 端 SSE：`EventSource` 只能发 GET，故参数走查询串。"""
        scenario = load_scenario(scenario_id)
        if scenario is None:
            raise HTTPException(status_code=404, detail="场景不存在")
        try:
            parsed = json.loads(answers or "{}")
        except ValueError:
            raise HTTPException(status_code=400, detail="answers 不是合法 JSON")
        return StreamingResponse(
            sse_stream(scenario, utterance, parsed),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/apply")
    def apply_stream_post(req: ApplyRequest):
        """与 GET 等价的 POST 形态（供 fetch 流式客户端使用）。"""
        scenario = load_scenario(req.scenario_id)
        if scenario is None:
            raise HTTPException(status_code=404, detail="场景不存在")
        return StreamingResponse(
            sse_stream(scenario, req.utterance, req.answers),
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

        loop = asyncio.get_running_loop()

        def pump():
            for event in iter_events(scenario, payload.get("utterance", ""), payload.get("answers") or {}):
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