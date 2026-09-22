"""FastAPI 请求 / 响应模型（Pydantic v2）。"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class SessionCreateRequest(BaseModel):
    scenario_id: str


class MessageRequest(BaseModel):
    session_id: str
    message: str


class FieldSubmitRequest(BaseModel):
    session_id: str
    key: str
    value: Any


class ApplyRequest(BaseModel):
    """一次性提交并开始办理（前端事件流入口）。"""
    scenario_id: str
    utterance: str = ""
    answers: Dict[str, Any] = {}


class FieldQuestion(BaseModel):
    key: str
    label: str
    type: str = "text"
    options: List[str] = []
    required: bool = True


class ProgressItem(BaseModel):
    item_id: str
    name: str
    status: str


class CaseOut(BaseModel):
    case_id: str
    scenario_id: str
    items: List[str]
    materials: List[str]
    verify_report: dict
    item_status: dict
    flow: List[dict] = []
    created_at: str
    updated_at: str = ""


class TurnResponse(BaseModel):
    session_id: str
    scenario_id: str
    scenario_name: str
    intent: str = ""
    message: str = ""
    next_question: Optional[FieldQuestion] = None
    items: List[str] = []
    materials: List[str] = []
    case: Optional[CaseOut] = None
    progress: List[ProgressItem] = []