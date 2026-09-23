"""单张材料的核验规则（纯函数，不依赖 Agent，便于单元测试）。

两级核验（见 docs/09）：

1. **形式校验**（规则，本地瞬时完成）：扩展名是否在被接受的格式里、文件是否为空、体积是否超限；
2. **内容核验**（真实实现调多模态模型 `qwen-vl`）：识别证件要素、与表单比对、判断清晰度。

桩阶段的内容核验用一条**可解释**的规则代替模型：图片体积过小判为"不是原图"。
这样既保留了「需补正」闭环，又不会误伤正常拍摄的照片——真实接入时把
`check_file` 的内容核验分支换成模型调用即可，调用方完全不用改。
"""
from typing import Any, Dict, List

from .spec import (DEFAULT_ACCEPT, DEFAULT_MAX_FILE_BYTES, FILE_NEED_FIX,
                   FILE_PASSED, PASSED, ext_of, status_of)

# 低于这个体积的图片视为缩略图 / 截图（真实实现改为清晰度模型判定）
MIN_IMAGE_BYTES = 5 * 1024
IMAGE_EXTS = ("jpg", "jpeg", "png")

RESULT_PASS = "通过"
RESULT_NEED_FIX = "需补正"
RESULT_REJECT = "不通过"


def check_file(spec: Dict[str, Any], filename: str, content: bytes) -> Dict[str, str]:
    """核验单张文件。

    返回 `{result, status, reason}`：

    - `result`：`通过 / 需补正 / 不通过`（不通过表示文件收不下，前端需重选）
    - `status`：写入文件记录的状态（仅 `通过` / `需补正` 两种）
    - `reason`：对用户可见的自然语言说明
    """
    accept = [item.lower() for item in (spec.get("accept") or DEFAULT_ACCEPT)]
    ext = ext_of(filename)

    if ext not in accept:
        return {"result": RESULT_REJECT, "status": "",
                "reason": "这个格式收不了，请上传 " + "/".join(accept) + "。"}
    if not content:
        return {"result": RESULT_REJECT, "status": "", "reason": "这个文件是空的，请重新选择。"}
    if len(content) > DEFAULT_MAX_FILE_BYTES:
        return {"result": RESULT_REJECT, "status": "",
                "reason": "单个文件不能超过 10MB，请压缩后再传。"}
    if ext in IMAGE_EXTS and len(content) < MIN_IMAGE_BYTES:
        return {"result": RESULT_NEED_FIX, "status": FILE_NEED_FIX,
                "reason": "这张图太小、看不清内容，请重拍原图。"}
    return {"result": RESULT_PASS, "status": FILE_PASSED, "reason": ""}


def review(specs: List[Dict[str, Any]], files_map: Dict[str, List[Any]], model: str = "") -> Dict[str, Any]:
    """整体核验报告：逐项结果 + 汇总，留档到办理单。"""
    results = []
    for spec in specs:
        files = files_map.get(spec["id"]) or []
        results.append({
            "material_id": spec["id"],
            "name": spec["name"],
            "status": status_of(spec, files),
            "files": len(files),
        })
    passed = sum(1 for item in results if item["status"] == PASSED)
    return {
        "status": RESULT_PASS if results and passed == len(results) else RESULT_NEED_FIX,
        "checked": len(results),
        "passed": passed,
        "results": results,
        "model": model,
    }
