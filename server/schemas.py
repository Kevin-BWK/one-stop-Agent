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
    """提交并开始办理（前端事件流入口）。

    带 `intake_id` 时表示材料已提交齐备，编排从「材料核验」续跑到办结；
    不带时按老行为一次跑完全程（CLI / 演示用）。
    带 `session_id`（多轮会话路径）时，编排结束后把办理单挂回该会话，
    使会话里的"进度查询"仍然可用。
    """
    scenario_id: str
    utterance: str = ""
    answers: Dict[str, Any] = {}
    intake_id: str = ""
    session_id: str = ""


class IntakeRequest(BaseModel):
    """填写完申请信息后，请求生成材料清单。"""
    scenario_id: str
    answers: Dict[str, Any] = {}


class AskRequest(BaseModel):
    """对话区提问（咨询意图）。"""
    scenario_id: str
    question: str
    session_id: str = ""


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
    # 材料 id 列表（结构化；给界面展示请用 material_view）
    materials: List[str] = []
    # 字段采齐后产出：材料收集单号 + 材料区渲染数据
    intake_id: str = ""
    material_view: Optional[dict] = None
    case: Optional[CaseOut] = None
    progress: List[ProgressItem] = []