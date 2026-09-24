"""FastAPI 请求 / 响应模型（Pydantic v2）。

这里是**前后端契约的服务端定义**：所有返回 JSON 的路由都应声明 `response_model`
（见 `server/main.py` / `server/materials.py`），这样契约不再只存在于前端
`frontend/src/types/contract.ts`；`tests/test_openapi_contract.py` 会拿
OpenAPI schema 与前端类型做一致性校验，防止后端改字段时前端静默坏掉。
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


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


class PreviewRequest(BaseModel):
    """填写过程中请求条件判定预判。

    只读、无状态：不建材料收集单、不落库，纯粹是"按目前填了多少先算一遍"。
    """
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


class FormOut(BaseModel):
    """申请表单：按场景字段采集到的结构化取值。"""
    scenario_id: str = ""
    fields: Dict[str, Any] = {}


class CaseOut(BaseModel):
    """办理单。

    `form` 只在「按单号读已落盘办理单」（`GET /api/cases/{case_id}`）时出现；
    多轮会话内嵌的 case 不带 form（见 `server/service.py::_case_dict`）。
    `owner_id` 为办理单归属用户，用于多用户隔离（见 `docs/12`）。
    """
    case_id: str
    scenario_id: str
    items: List[str]
    materials: List[str]
    verify_report: dict
    item_status: dict
    flow: List[dict] = []
    created_at: str
    updated_at: str = ""
    owner_id: str = ""
    form: Optional[FormOut] = None


class MaterialSummaryOut(BaseModel):
    """材料整体进度：必交材料通过数 / 是否齐备可提交。"""
    total: int
    passed: int
    ready: bool


class MaterialFileOut(BaseModel):
    """用户已提交的单个文件。"""
    file_id: str
    slot: str = ""
    filename: str = ""
    stored_name: str = ""
    size: int = 0
    content_type: str = ""
    status: str = ""
    reason: str = ""
    uploaded_at: str = ""
    url: str = ""


class MaterialItemOut(BaseModel):
    """一种材料：清单信息 + 提交状态 + 已传文件。"""
    id: str
    name: str
    reason: str = ""
    form: str = ""
    accept: List[str] = []
    slots: List[str] = []
    multiple: bool = False
    max_files: int = 1
    required: bool = True
    status: str = ""
    missing_slots: List[str] = []
    files: List[MaterialFileOut] = []


class MaterialViewOut(BaseModel):
    """材料收集单视图：材料接口与材料区渲染的统一返回。"""
    intake_id: str
    scenario_id: str
    items: List[str] = []
    notes: List[str] = []
    summary: MaterialSummaryOut
    materials: List[MaterialItemOut] = []
    message: str = ""


class PreviewOut(BaseModel):
    """条件判定实时预判（POST /api/preview）；只读、无副作用。"""
    items: List[str] = []
    item_names: List[str] = []
    materials: List[str] = []
    material_names: List[str] = []
    notes: List[str] = []


class ScenarioOut(BaseModel):
    """场景配置（`scenarios/*.json`）。

    "配置即业务"——场景 JSON 会随业务演进加字段，所以这里只声明前端要用到的键，
    其余原样透传（`extra="allow"`），避免加了 response_model 反而把配置字段裁掉。
    """
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    opening: str = ""
    guide: str = ""
    collect_fields: List[Dict[str, Any]] = []
    items: Dict[str, Dict[str, Any]] = {}


class HealthOut(BaseModel):
    """健康检查；`moma` 为模型客户端当前模式（live / stub）。

    `storage` 为当前存储后端、`auth_required` 为是否强制登录（见 `docs/12`）：
    上线前用来一眼确认"跑的是不是多用户形态"，两者都不含任何密钥。
    """
    status: str
    moma: str
    storage: str = ""
    auth_required: bool = False


class RegisterRequest(BaseModel):
    """注册办事账号。"""
    username: str
    password: str
    display_name: str = ""


class LoginRequest(BaseModel):
    """账号口令登录。"""
    username: str
    password: str


class UserOut(BaseModel):
    """用户对外视图（**不含口令与哈希**）。"""
    user_id: str
    username: str
    display_name: str = ""
    role: str = "applicant"
    created_at: str = ""


class TokenOut(BaseModel):
    """登录结果：自包含令牌 + 用户信息（客户端存 token，后续放 `Authorization`）。"""
    token: str
    token_type: str = "Bearer"
    expires_in: int = 0
    user: UserOut


class AskResponse(BaseModel):
    """对话区提问的回答。"""
    question: str
    answer: str


class EventOut(BaseModel):
    """编排事件外壳（SSE / WebSocket 推送，见 `docs/07`）。"""
    type: str
    data: Dict[str, Any] = {}


class TurnResponse(BaseModel):
    """会话一次交互的完整状态（/api/session、/api/chat、/api/fields 共用）。"""
    session_id: str
    scenario_id: str
    scenario_name: str
    intent: str = ""
    message: str = ""
    next_question: Optional[FieldQuestion] = None
    items: List[str] = []
    # 材料 id 列表（结构化；给界面展示请用 material_view）
    materials: List[str] = []
    # 按当前已填字段的实时预判（只读；字段采齐后与正式清单一致）
    preview: Optional[PreviewOut] = None
    # 字段采齐后产出：材料收集单号 + 材料区渲染数据
    intake_id: str = ""
    material_view: Optional[MaterialViewOut] = None
    case: Optional[CaseOut] = None
    progress: List[ProgressItem] = []