"""材料提交：受理前的材料清单、上传通道与逐项核验。

注意：这里**不导入** `service`（它依赖 agents 层），需要业务入口请显式：
    from app.materials.service import MaterialService
"""
from .spec import (FILE_NEED_FIX, FILE_PASSED, NEED_FIX, PASSED, PENDING,
                   material_specs, status_of, summary)
from .store import MaterialStore

__all__ = [
    "MaterialStore",
    "material_specs",
    "status_of",
    "summary",
    "PENDING",
    "PASSED",
    "NEED_FIX",
    "FILE_PASSED",
    "FILE_NEED_FIX",
]
