"""材料落盘存储：材料收集单 + 用户上传的文件。

落盘位置（`data/runtime/` 已在 .gitignore 中）：

    data/runtime/intakes.json                                       材料收集单索引
    data/runtime/materials/{intake_id}/{material_id}/{file_id}.{ext} 用户上传的文件

桩阶段直接写本地磁盘，真实阶段把 `add_file` 换成对象存储上传即可，
接口与调用方（`MaterialService`）都不用改。
"""
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from ..config import ROOT
from ..models.schema import MaterialFile, MaterialIntake
from ..storage.atomic import read_json, write_json
from ..storage.ids import IdAllocator, InMemoryIdAllocator, sequence_of
from .spec import FILE_NEED_FIX, ext_of

RUNTIME_DIR = ROOT / "data" / "runtime"
INTAKES_FILE = RUNTIME_DIR / "intakes.json"
MATERIALS_DIR = RUNTIME_DIR / "materials"


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class MaterialStore:
    """材料收集单与上传文件的读写。

    单号由 `IdAllocator` 生成（见 `app/storage/ids.py`）：进程内实现用于 Demo，
    落盘 / 数据库实现用于多进程——生产把 `add_file` 换成对象存储上传即可，
    接口与调用方（`MaterialService`）都不用改。
    """

    def __init__(self, intakes_file=None, materials_dir=None, ids: IdAllocator = None):
        self.intakes_file = Path(intakes_file) if intakes_file else INTAKES_FILE
        self.materials_dir = Path(materials_dir) if materials_dir else MATERIALS_DIR
        self.ids = ids if ids is not None else InMemoryIdAllocator()
        self._intakes: Dict[str, MaterialIntake] = {}
        self._load()

    # ---------- 收集单 ----------

    def _load(self):
        data = read_json(self.intakes_file, {}) or {}
        for item in data.get("intakes") or []:
            try:
                intake = MaterialIntake.from_dict(item)
            except (KeyError, TypeError, ValueError):
                continue
            self._intakes[intake.intake_id] = intake
        # 对齐历史最大号，避免重启后重号
        self.ids.reserve("CL", max([sequence_of(key) for key in self._intakes] or [0]))

    def _save(self):
        write_json(self.intakes_file,
                   {"intakes": [item.to_dict() for item in self._intakes.values()]})

    def create(self, scenario_id: str, form, items, materials, notes,
               owner_id: str = "") -> MaterialIntake:
        intake = MaterialIntake(
            intake_id=self.ids.next("CL", 4),
            scenario_id=scenario_id,
            form=form,
            items=list(items),
            materials=list(materials),
            notes=list(notes),
            files={},
            created_at=_now(),
            updated_at=_now(),
            owner_id=owner_id,
        )
        self._intakes[intake.intake_id] = intake
        self._save()
        return intake

    def get(self, intake_id: str) -> Optional[MaterialIntake]:
        return self._intakes.get(intake_id)

    def list_intakes(self) -> List[MaterialIntake]:
        return list(self._intakes.values())

    def touch(self, intake: MaterialIntake) -> MaterialIntake:
        intake.updated_at = _now()
        self._save()
        return intake

    # ---------- 上传文件 ----------

    def dir_of(self, intake_id: str, material_id: str) -> Path:
        return self.materials_dir / intake_id / material_id

    def add_file(self, intake: MaterialIntake, material_id: str, filename: str,
                 content_type: str, content: bytes, slot: str = "",
                 status: str = "", reason: str = "") -> MaterialFile:
        file_id = uuid.uuid4().hex[:12]
        ext = ext_of(filename)
        stored_name = file_id + ("." + ext if ext else "")
        target_dir = self.dir_of(intake.intake_id, material_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / stored_name).write_bytes(content)

        record = MaterialFile(
            file_id=file_id,
            slot=slot,
            filename=filename or stored_name,
            stored_name=stored_name,
            size=len(content),
            content_type=content_type or "",
            status=status,
            reason=reason,
            uploaded_at=_now(),
        )
        intake.files.setdefault(material_id, []).append(record)
        self.touch(intake)
        return record

    def path_of(self, intake: MaterialIntake, material_id: str, file_id: str) -> Optional[Path]:
        for record in intake.files_of(material_id):
            if record.file_id == file_id:
                path = self.dir_of(intake.intake_id, material_id) / record.stored_name
                return path if path.exists() else None
        return None

    def find(self, intake_id: str, material_id: str, file_id: str):
        """按受理号 + 材料 + 文件定位；返回 (intake, record)，找不到对应项为 None。"""
        intake = self.get(intake_id)
        if intake is None:
            return None, None
        for record in intake.files_of(material_id):
            if record.file_id == file_id:
                return intake, record
        return intake, None

    def remove_file(self, intake: MaterialIntake, material_id: str, file_id: str) -> bool:
        group = intake.files.get(material_id) or []
        for record in list(group):
            if record.file_id != file_id:
                continue
            path = self.dir_of(intake.intake_id, material_id) / record.stored_name
            if path.exists():
                path.unlink()
            group.remove(record)
            self.touch(intake)
            return True
        return False

    def remove_needs_fix(self, intake: MaterialIntake, material_id: str, slot: str) -> int:
        """清掉某个槽位上"需补正"的旧文件（重传时先占位替换）。"""
        group = intake.files.get(material_id) or []
        removed = 0
        for record in list(group):
            if record.slot == slot and record.status == FILE_NEED_FIX:
                path = self.dir_of(intake.intake_id, material_id) / record.stored_name
                if path.exists():
                    path.unlink()
                group.remove(record)
                removed += 1
        if removed:
            self.touch(intake)
        return removed


_default_store: Optional[MaterialStore] = None


def get_store() -> MaterialStore:
    """进程内共享的存储实例。

    服务层多处（HTTP 路由 / 事件流）都要读写材料，共用同一个实例才能
    保证内存缓存与磁盘文件一致。
    """
    global _default_store
    if _default_store is None:
        _default_store = MaterialStore()
    return _default_store

