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
    # 办理单归属的用户（多用户隔离；空串表示历史 / 演示数据）
    owner_id: str = ""

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
            "owner_id": self.owner_id,
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
            owner_id=data.get("owner_id", ""),
        )


@dataclass
class MaterialFile:
    """一份材料下用户已提交的单个文件。

    落盘位置：data/runtime/materials/{intake_id}/{material_id}/{stored_name}
    """
    file_id: str
    slot: str               # 具名槽位（如"正面"）；多页材料为空串
    filename: str           # 用户原始文件名（仅用于展示）
    stored_name: str        # 实际落盘文件名
    size: int
    content_type: str = ""
    status: str = ""        # 已通过 / 需补正
    reason: str = ""        # 需补正原因（对用户可见的自然语言）
    uploaded_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_id": self.file_id,
            "slot": self.slot,
            "filename": self.filename,
            "stored_name": self.stored_name,
            "size": self.size,
            "content_type": self.content_type,
            "status": self.status,
            "reason": self.reason,
            "uploaded_at": self.uploaded_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MaterialFile":
        return cls(
            file_id=data["file_id"],
            slot=data.get("slot", ""),
            filename=data.get("filename", ""),
            stored_name=data.get("stored_name", ""),
            size=int(data.get("size") or 0),
            content_type=data.get("content_type", ""),
            status=data.get("status", ""),
            reason=data.get("reason", ""),
            uploaded_at=data.get("uploaded_at", ""),
        )


@dataclass
class MaterialIntake:
    """材料收集单：受理**之前**收集材料的凭据。

    与办理单 CaseRecord 解耦：材料清单依赖条件判定，判定又发生在提交之前，
    因此材料先落在 intake 上，材料齐了才由 /apply 生成办理单。
    """
    intake_id: str
    scenario_id: str
    form: ApplicationForm
    items: List[str] = field(default_factory=list)
    materials: List[str] = field(default_factory=list)   # 材料 id（条件判定的产物）
    notes: List[str] = field(default_factory=list)
    files: Dict[str, List[MaterialFile]] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    # 材料收集单归属的用户（材料属敏感个人信息，读取必须校验归属）
    owner_id: str = ""

    def files_of(self, material_id: str) -> List[MaterialFile]:
        return list(self.files.get(material_id) or [])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intake_id": self.intake_id,
            "scenario_id": self.scenario_id,
            "form": self.form.to_dict(),
            "items": list(self.items),
            "materials": list(self.materials),
            "notes": list(self.notes),
            "files": {
                material_id: [item.to_dict() for item in group]
                for material_id, group in self.files.items()
            },
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "owner_id": self.owner_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MaterialIntake":
        files: Dict[str, List[MaterialFile]] = {}
        for material_id, group in (data.get("files") or {}).items():
            files[material_id] = [MaterialFile.from_dict(item) for item in group]
        return cls(
            intake_id=data["intake_id"],
            scenario_id=data.get("scenario_id", ""),
            form=ApplicationForm.from_dict(data.get("form")),
            items=list(data.get("items") or []),
            materials=list(data.get("materials") or []),
            notes=list(data.get("notes") or []),
            files=files,
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            owner_id=data.get("owner_id", ""),
        )
