"""核心数据模型（纯标准库 dataclass，保证骨架零依赖可运行）。"""
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ApplicationForm:
    """一次申请表单：按场景字段收集的结构化数据。"""
    scenario_id: str
    fields: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CaseRecord:
    """办理单：并联办理与进度的载体。"""
    case_id: str
    scenario_id: str
    form: ApplicationForm
    items: List[str] = field(default_factory=list)
    materials: List[str] = field(default_factory=list)
    verify_report: Dict[str, Any] = field(default_factory=dict)
    item_status: Dict[str, str] = field(default_factory=dict)
    created_at: str = ""
