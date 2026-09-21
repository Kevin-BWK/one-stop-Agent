"""核心数据模型（纯标准库 dataclass，保证骨架零依赖可运行）。"""
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ApplicationForm:
    """一次申请表单：按场景字段收集的结构化数据。"""
    scenario_id: str
    fields: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"scenario_id": self.scenario_id, "fields": dict(self.fields)}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ApplicationForm":
        data = data or {}
        return cls(scenario_id=data.get("scenario_id", ""), fields=dict(data.get("fields") or {}))


@dataclass
class CaseRecord:
    """办理单：并联办理与进度的载体。

    flow 为办理流程节点台账（见 app/orchestrator/flow.py），
    每个节点完成即"打勾"，是"办理进度"的主线；
    item_status 为并联到各部门的事项状态。
    """
    case_id: str
    scenario_id: str
    form: ApplicationForm
    items: List[str] = field(default_factory=list)
    materials: List[str] = field(default_factory=list)
    verify_report: Dict[str, Any] = field(default_factory=dict)
    item_status: Dict[str, str] = field(default_factory=dict)
    flow: List[Dict[str, str]] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "scenario_id": self.scenario_id,
            "form": self.form.to_dict(),
            "items": list(self.items),
            "materials": list(self.materials),
            "verify_report": dict(self.verify_report),
            "item_status": dict(self.item_status),
            "flow": [dict(node) for node in self.flow],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CaseRecord":
        return cls(
            case_id=data["case_id"],
            scenario_id=data.get("scenario_id", ""),
            form=ApplicationForm.from_dict(data.get("form")),
            items=list(data.get("items") or []),
            materials=list(data.get("materials") or []),
            verify_report=dict(data.get("verify_report") or {}),
            item_status=dict(data.get("item_status") or {}),
            flow=[dict(node) for node in (data.get("flow") or [])],
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )
