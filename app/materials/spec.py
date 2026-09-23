"""材料条目规则：解析场景里的材料清单，并判定每项材料的状态。

一份材料有两种形态（由 `slots` 决定）：

- **具名槽位**（`slots: ["正面", "反面"]`）：每个槽位恰好一张，总张数即槽位数。
  典型是身份证正反面——缺一张不算齐，多传一概不收。
- **多页材料**（`slots: []` + `multiple: true`）：同一份材料不固定页数，
  按 `max_files` 设上限（如多页合同、多页章程）。

状态机（每项材料）：

    待提交 --(槽位齐且核验通过)--> 已通过
       \\--(有文件核验不过)--> 需补正 --(重传该项)--> 待提交/已通过
"""
from typing import Any, Dict, List, Optional

# 材料状态
PENDING = "待提交"
PASSED = "已通过"
NEED_FIX = "需补正"

# 单张文件的状态
FILE_PASSED = "已通过"
FILE_NEED_FIX = "需补正"

# 兜底限制（场景未声明时使用）
DEFAULT_ACCEPT = ["jpg", "jpeg", "png", "pdf"]
DEFAULT_MAX_FILE_BYTES = 10 * 1024 * 1024


def material_specs(scenario: Dict[str, Any], material_ids: List[str]) -> List[Dict[str, Any]]:
    """按 id 取出材料条目（保持 `material_ids` 顺序），并补齐默认字段。"""
    catalog = scenario.get("materials") or {}
    specs = []
    for material_id in material_ids:
        spec = dict(catalog.get(material_id) or {})
        spec["id"] = material_id
        spec.setdefault("name", material_id)
        spec.setdefault("reason", "")
        spec.setdefault("form", "")
        spec.setdefault("accept", list(DEFAULT_ACCEPT))
        spec.setdefault("required", True)
        slots = list(spec.get("slots") or [])
        spec["slots"] = slots
        if slots:
            # 具名槽位：一槽一张，槽位数就是张数上限
            spec["multiple"] = False
            spec["max_files"] = len(slots)
        else:
            # 多页材料：不固定页数，受 max_files 约束
            spec["multiple"] = True
            spec["max_files"] = int(spec.get("max_files") or 1)
        specs.append(spec)
    return specs


def capacity(spec: Dict[str, Any]) -> int:
    """这份材料最多能收几张。"""
    return int(spec.get("max_files") or 1)


def ext_of(filename: str) -> str:
    """取小写扩展名（不含点）。"""
    name = (filename or "").strip().lower()
    return name.rsplit(".", 1)[-1] if "." in name else ""


def usable_files(files: List[Any]) -> List[Any]:
    """核验通过、真正占位的文件（需补正的不算数，用户可原地重传）。"""
    return [item for item in files if item.status != FILE_NEED_FIX]


def missing_slots(spec: Dict[str, Any], files: List[Any]) -> List[str]:
    """还缺哪些槽位（多页材料返回 `["至少 1 张"]`）。"""
    usable = usable_files(files)
    if spec.get("multiple"):
        return [] if usable else ["至少 1 张"]
    used = {item.slot for item in usable}
    return [label for label in spec["slots"] if label not in used]


def status_of(spec: Dict[str, Any], files: List[Any]) -> str:
    """判定一份材料当前状态。"""
    if any(item.status == FILE_NEED_FIX for item in files):
        return NEED_FIX
    if missing_slots(spec, files):
        return PENDING
    return PASSED


def reject_reason(spec: Dict[str, Any], files: List[Any], slot: str) -> Optional[str]:
    """能否再收一张；返回拒绝原因（对用户可见），可以收则返回 None。"""
    usable = usable_files(files)
    if len(usable) >= capacity(spec):
        return ("「" + spec["name"] + "」一共只需 " + str(capacity(spec))
                + " 张，已经收满了，多的不收。")
    labels = spec.get("slots") or []
    if not labels:
        return None
    if not slot:
        return "请指明这一张对应的是：" + "、".join(labels) + "。"
    if slot not in labels:
        return "「" + spec["name"] + "」只收：" + "、".join(labels) + "。"
    if any(item.slot == slot for item in usable):
        return "「" + slot + "」已经交过了。要换一张，请先撤回原来那张。"
    return None


def summary(specs: List[Dict[str, Any]], files_map: Dict[str, List[Any]]) -> Dict[str, Any]:
    """整体进度：必交材料里有几项已通过、是否齐备可提交。"""
    required = [spec for spec in specs if spec.get("required", True)]
    passed = 0
    for spec in required:
        if status_of(spec, files_map.get(spec["id"]) or []) == PASSED:
            passed += 1
    return {
        "total": len(required),
        "passed": passed,
        "ready": bool(required) and passed == len(required),
    }


def describe_lines(specs: List[Dict[str, Any]]) -> List[str]:
    """逐项说明"要什么、为什么、怎么给"，用于对话区播报。"""
    lines = []
    for index, spec in enumerate(specs, start=1):
        head = "【材料 " + str(index) + "/" + str(len(specs)) + "】" + spec["name"]
        if not spec.get("required", True):
            head += "（选交）"
        parts = [head]
        if spec.get("reason"):
            parts.append("· 为什么：" + spec["reason"])
        if spec.get("form"):
            parts.append("· 怎么给：" + spec["form"])
        if spec.get("slots"):
            parts.append("· 份数：" + str(len(spec["slots"])) + " 张（" + "、".join(spec["slots"]) + "）")
        else:
            parts.append("· 份数：1 ~ " + str(capacity(spec)) + " 张")
        parts.append("· 格式：" + "/".join(spec.get("accept") or DEFAULT_ACCEPT))
        lines.append("\n".join(parts))
    return lines
