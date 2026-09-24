"""FastAPI 入口：把 AgentService 暴露为 HTTP 接口。

运行（在项目根目录）：
    pip install -r requirements.txt
    uvicorn server.main:app --reload

多用户与鉴权（见 `docs/12`）：
- 存储由 `app/storage/factory.py::build_storage()` 统一装配（默认 JSON 文件，
  生产换 `STORAGE_BACKEND=sql/redis` 并注入实现即可，业务代码零改动）；
- 会话 / 材料收集单 / 办理单都记录归属用户，接口按归属校验（RBAC）；
- `AUTH_REQUIRED=1` 时强制登录；默认关闭，未登录请求按演示用户处理，
  单用户 Demo 行为不变。

用例（多用户）：`create_app(storage=build_storage("memory"), auth=AuthService(required=True))`。
"""
import asyncio
import json

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from app.auth.models import User
from app.auth.service import AuthService
from app.orchestrator.preview import build_preview
from app.storage.factory import build_storage

from .auth import build_auth_router, ensure_access, make_user_dependency, resolve_user
from .materials import build_router
from .schemas import (ApplyRequest, AskRequest, AskResponse, CaseOut, FieldSubmitRequest,
                      HealthOut, MessageRequest, PreviewOut, PreviewRequest, ScenarioOut,
                      SessionCreateRequest, TurnResponse)
from .service import AgentService
from .stream import (answer_question, iter_events, load_case, load_intake,
                     load_scenario, material_gate, missing_required, sse_stream)


def create_app(storage=None, auth: AuthService = None) -> FastAPI:
    """装配应用。

    `storage` / `auth` 可注入（测试与真实部署用）；不传时按 `STORAGE_BACKEND`
    与默认鉴权服务装配，行为与单机 Demo 一致。
    """
    app = FastAPI(title="one-stop-agent API", version="0.1.0")

    storage = storage or build_storage()
    auth = auth or AuthService(store=storage.users)
    service = AgentService(cases=storage.cases, sessions=storage.sessions,
                           ids=storage.ids, store=storage.materials,
                           url_signer=auth.issue_file_token)
    app.state.storage = storage
    app.state.auth = auth
    app.state.service = service
    app.include_router(build_router(service=service.materials, auth=auth))
    app.include_router(build_auth_router(auth))

    current_user = make_user_dependency(auth)

    def current_session_user(request) -> User:
        """WebSocket 等无法用 `Depends` 的入口：手动解析当前用户。"""
        user = resolve_user(request, auth)
        if user is None:
            raise HTTPException(status_code=401, detail="请先登录")
        return user

    def guard_session(session_id: str, user: User) -> None:
        """会话归属校验：不存在 404，不是本人（且无跨用户权限）403。

        跨用户权限用 `session:any`——会话里是**未受理的草稿信息**，
        工作人员只有 `case:any`（可查已受理的办理单），读不到别人的草稿。
        """
        try:
            owner = service.owner_of(session_id)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e).strip("'\""))
        ensure_access(user, owner, permission="session:any")

    def intake_or_400(intake_id, user: User):
        """受理前置校验：材料没交齐就不允许开始办理；并校验归属。"""
        if not intake_id:
            return None
        intake = load_intake(intake_id, store=storage.materials)
        if intake is None:
            raise HTTPException(status_code=404, detail="材料受理号不存在：" + intake_id)
        ensure_access(user, intake.owner_id, permission="material:any")
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

    @app.get("/health", response_model=HealthOut)
    def health():
        return {"status": "ok", "moma": service.moma.mode(),
                "storage": storage.backend, "auth_required": auth.required}

    @app.post("/api/session", response_model=TurnResponse)
    def create_session(req: SessionCreateRequest, user: User = Depends(current_user)):
        try:
            return service.create_session(req.scenario_id, user_id=user.user_id)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @app.post("/api/chat", response_model=TurnResponse)
    def chat(req: MessageRequest, user: User = Depends(current_user)):
        guard_session(req.session_id, user)
        try:
            return service.handle_message(req.session_id, req.message)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @app.post("/api/fields", response_model=TurnResponse)
    def submit_field(req: FieldSubmitRequest, user: User = Depends(current_user)):
        guard_session(req.session_id, user)
        try:
            return service.submit_field(req.session_id, req.key, req.value)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/cases/{case_id}", response_model=CaseOut)
    def get_case(case_id: str, user: User = Depends(current_user)):
        # 事件流办理单落盘在 data/runtime/cases.json；多轮会话办理单在 service 内存里
        case = load_case(case_id, repo=storage.cases)
        if case is None:
            case = service.get_case(case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="办理单不存在")
        ensure_access(user, (case or {}).get("owner_id", ""))
        return case

    @app.get("/api/sessions/{session_id}", response_model=TurnResponse)
    def get_session(session_id: str, user: User = Depends(current_user)):
        guard_session(session_id, user)
        try:
            return service.get_session(session_id)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))

    # ---------- 前端事件流（一次性提交并开始办理）----------
    # App（成品端）：WebSocket；H5（调试端）：SSE。两端事件负载格式一致。

    @app.get("/scenarios/{scenario_id}", response_model=ScenarioOut)
    def get_scenario(scenario_id: str):
        scenario = load_scenario(scenario_id)
        if scenario is None:
            raise HTTPException(status_code=404, detail="场景不存在")
        return scenario

    @app.post("/api/preview", response_model=PreviewOut)
    def preview(req: PreviewRequest):
        """条件判定实时预判：按当前（可能还不完整的）表单预估事项与材料。

        只读、无状态：不建材料收集单、不落库，纯函数求值，可任意频率调用。
        不涉及用户数据，因此不做鉴权（上线前可按需收紧）。
        """
        scenario = load_scenario(req.scenario_id)
        if scenario is None:
            raise HTTPException(status_code=404, detail="场景不存在")
        return build_preview(scenario, req.answers)

    @app.post("/api/ask", response_model=AskResponse)
    def ask(req: AskRequest, user: User = Depends(current_user)):
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
            guard_session(req.session_id, user)
            try:
                context = service.context_of(req.session_id)
            except KeyError as e:
                raise HTTPException(status_code=404, detail=str(e))
        return {"question": question,
                "answer": answer_question(scenario, question, context, service.knowledge)}

    @app.get("/apply")
    def apply_stream(scenario_id: str, utterance: str = "", answers: str = "{}",
                     intake_id: str = "", session_id: str = "",
                     user: User = Depends(current_user)):
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
        if session_id:
            guard_session(session_id, user)
        intake = intake_or_400(intake_id, user)
        intake_guard(scenario, intake)
        return StreamingResponse(
            sse_stream(scenario, utterance, parsed, intake, attach_hook(session_id),
                       owner_id=_owner_of(intake, user), repo=storage.cases, ids=storage.ids),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/apply")
    def apply_stream_post(req: ApplyRequest, user: User = Depends(current_user)):
        """与 GET 等价的 POST 形态（供 fetch 流式客户端使用）。"""
        scenario = load_scenario(req.scenario_id)
        if scenario is None:
            raise HTTPException(status_code=404, detail="场景不存在")
        missing = missing_required(scenario, req.answers)
        if missing:
            raise HTTPException(status_code=400, detail="还缺这些必填信息：" + "、".join(missing))
        if req.session_id:
            guard_session(req.session_id, user)
        intake = intake_or_400(req.intake_id, user)
        intake_guard(scenario, intake)
        return StreamingResponse(
            sse_stream(scenario, req.utterance, req.answers, intake,
                       attach_hook(req.session_id), owner_id=_owner_of(intake, user),
                       repo=storage.cases, ids=storage.ids),
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
            user = current_session_user(websocket)
            if payload.get("session_id"):
                guard_session(payload["session_id"], user)
            intake = intake_or_400(payload.get("intake_id", ""), user)
            intake_guard(scenario, intake)
        except HTTPException as exc:
            await websocket.send_json(
                {"type": "error", "data": {"code": "Unauthorized" if exc.status_code == 401
                                           else "BadRequest", "message": str(exc.detail)}})
            await websocket.close()
            return

        loop = asyncio.get_running_loop()
        hook = attach_hook(payload.get("session_id", ""))
        owner_id = _owner_of(intake, user)

        def pump():
            for event in iter_events(scenario, payload.get("utterance", ""),
                                     payload.get("answers") or {}, intake, hook,
                                     owner_id=owner_id, repo=storage.cases, ids=storage.ids):
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


def _owner_of(intake, user: User) -> str:
    """办理单归属：优先沿用收集单归属，历史数据（空归属）时落到当前用户。"""
    return (getattr(intake, "owner_id", "") or user.user_id) if intake is not None else user.user_id


app = create_app()
