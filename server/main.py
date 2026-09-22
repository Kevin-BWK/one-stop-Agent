"""FastAPI 入口：把 AgentService 暴露为 HTTP 接口。

运行（在项目根目录）：
    pip install -r requirements.txt
    uvicorn server.main:app --reload
"""
from fastapi import FastAPI, HTTPException

from .schemas import FieldSubmitRequest, MessageRequest, SessionCreateRequest
from .service import AgentService


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

    return app


app = create_app()