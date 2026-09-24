"""单张材料的核验规则与**可插拔的内容核验器**（见 `docs/09`）。

分两级：

1. **形式校验**（`form_check`）：纯规则、本地瞬时完成——扩展名、空文件、体积上限。
   不合格直接 `不通过`（文件收不下，前端要重选）；
2. **内容核验**（核验器）：这份材料的照片**是不是真是那份材料**、清不清晰。

内容核验按"当前有没有可用的多模态模型"自动选实现：

- `VisionChecker`：调用 MoMA 视觉模型（`qwen-vl`）看图判断；
- `StubChecker`：一条可解释的规则代替模型（图片过小判为"不是原图"），
  零依赖、离线可跑，且保留「需补正」闭环。

**降级策略（很重要）**：模型不可用 / 超时 / 返回无法解析 → 一律**回落桩规则**。
材料核验是办事链路的必经环节，不能因为模型故障就让群众交不上材料。

判定语义：

- `通过`   —— 收下，该槽位占位；
- `需补正` —— 收下但标记需补正，用户可原地重传（**"内容不对/看不清"属于这一类**）；
- `不通过` —— 文件根本收不下（格式 / 体积），前端要重选。
"""
import base64
import json
import re
from typing import Any, Dict, List, Optional

from .spec import (DEFAULT_ACCEPT, DEFAULT_MAX_FILE_BYTES, FILE_NEED_FIX,
                   FILE_PASSED, PASSED, ext_of, status_of)

RESULT_PASS = "通过"
RESULT_NEED_FIX = "需补正"
RESULT_REJECT = "不通过"

# 低于这个体积的图片视为缩略图 / 截图（桩规则用；清晰度判定交给视觉模型）
MIN_IMAGE_BYTES = 5 * 1024
IMAGE_EXTS = ("jpg", "jpeg", "png")

# 超过这个体积就不送模型：base64 后请求体会再膨胀约 1/3，得不偿失，回落桩规则
VISION_MAX_BYTES = 2 * 1024 * 1024

_MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}
_JSON_BLOCK = re.compile(r"\{.*\}", re.S)
_TRUE_WORDS = ("true", "yes", "ok", "1", "是", "通过", "合规", "符合")


def _passed() -> Dict[str, str]:
    return {"result": RESULT_PASS, "status": FILE_PASSED, "reason": ""}


def _need_fix(reason: str) -> Dict[str, str]:
    return {"result": RESULT_NEED_FIX, "status": FILE_NEED_FIX, "reason": reason}


def _reject(reason: str) -> Dict[str, str]:
    return {"result": RESULT_REJECT, "status": "", "reason": reason}


def form_check(spec: Dict[str, Any], filename: str, content: bytes) -> Optional[Dict[str, str]]:
    """形式校验：合格返回 `None`，不合格返回拒绝结果。"""
    accept = [item.lower() for item in (spec.get("accept") or DEFAULT_ACCEPT)]
    ext = ext_of(filename)
    if ext not in accept:
        return _reject("这个格式收不了，请上传 " + "/".join(accept) + "。")
    if not content:
        return _reject("这个文件是空的，请重新选择。")
    if len(content) > DEFAULT_MAX_FILE_BYTES:
        return _reject("单个文件不能超过 10MB，请压缩后再传。")
    return None


class StubChecker:
    """无模型时的内容核验：一条可解释的规则，保留「需补正」闭环。"""

    def check(self, spec: Dict[str, Any], filename: str, content: bytes,
              slot: str = "") -> Dict[str, str]:
        if ext_of(filename) in IMAGE_EXTS and len(content) < MIN_IMAGE_BYTES:
            return _need_fix("这张图太小、看不清内容，请重拍原图。")
        return _passed()


def data_url(ext: str, content: bytes) -> str:
    """把图片编码成 `data:` URL（零依赖；真实生产可改为上传对象存储后给外链）。"""
    mime = _MIME.get(ext, "image/jpeg")
    return "data:" + mime + ";base64," + base64.b64encode(content).decode("ascii")


def parse_verdict(reply: Any) -> Optional[Dict[str, Any]]:
    """从模型回复里取出 `{ok, reason}`；取不到返回 `None`（调用方据此回落桩规则）。

    模型常把 JSON 包在 ```json 代码块里、或前后带些解释文字，所以先用正则抓第一个
    对象再严格解析——**宁可回落桩规则，也不要把半截结果当结论**。
    """
    match = _JSON_BLOCK.search(str(reply or ""))
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict) or "ok" not in data:
        return None
    ok = data.get("ok")
    if isinstance(ok, str):
        ok = ok.strip().lower() in _TRUE_WORDS
    return {"ok": bool(ok), "reason": str(data.get("reason") or "").strip()}


class VisionChecker:
    """接了多模态模型的核验：看图判断是不是该材料的合规件。

    只在"是图片、且体积可承受"时才真的调模型；其余（非图片 / 图太大 / 模型不可用 /
    返回无法解析）一律回落桩规则。
    """

    def __init__(self, moma, model: str = "", role: str = "sub", fallback=None):
        self.moma = moma
        self.model = model or "qwen-vl"
        self.role = role
        self.fallback = fallback or StubChecker()

    def check(self, spec: Dict[str, Any], filename: str, content: bytes,
              slot: str = "") -> Dict[str, str]:
        ext = ext_of(filename)
        if ext not in IMAGE_EXTS or len(content) > VISION_MAX_BYTES:
            return self.fallback.check(spec, filename, content, slot)

        try:
            reply = self.moma.complete(
                self.model,
                self.messages(spec, slot, ext, content),
                fallback="",        # 桩模式只会拿到空串 -> 解析失败 -> 回落桩规则
                role=self.role,
            )
        except Exception:
            # 模型故障不该卡住办事：交材料这条链路必须能走下去
            return self.fallback.check(spec, filename, content, slot)

        verdict = parse_verdict(reply)
        if verdict is None:
            return self.fallback.check(spec, filename, content, slot)
        if verdict["ok"]:
            return _passed()
        return _need_fix(self.describe_rejection(spec, slot, verdict["reason"]))

    @staticmethod
    def messages(spec: Dict[str, Any], slot: str, ext: str, content: bytes) -> List[Dict[str, Any]]:
        """构造多模态消息（OpenAI 兼容：`content` 为数组，含文本与图片 data URL）。"""
        label = "「" + str(spec.get("name", "")) + "」"
        if slot:
            label = label + "的「" + slot + "」"
        system = (
            "你是政务办事材料审核助手，判断用户上传的图片是不是一张合规的办事材料照片。"
            "看不清、明显是别的物件、是屏幕翻拍或截图、被严重遮挡——都算不合规。"
            "只输出一个 JSON 对象，形如 {\"ok\": true, \"reason\": \"一句话中文原因\"}，"
            "ok 为 true 表示合规。不要输出 JSON 以外的任何内容。"
        )
        ask = (
            "这份材料是" + label + "。"
            "它在办理中的用途是：" + (spec.get("reason") or "证明相关事实") + "。"
            "请判断这张图是不是一张合规的" + label + "照片。"
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "text", "text": ask},
                {"type": "image_url", "image_url": {"url": data_url(ext, content)}},
            ]},
        ]

    @staticmethod
    def describe_rejection(spec: Dict[str, Any], slot: str, model_reason: str) -> str:
        """把模型的判断说成群众看得懂的一句话（不暴露模型名与内部 id）。"""
        what = "「" + str(spec.get("name", "")) + "」"
        if slot:
            what = what + "的「" + slot + "」"
        text = "这张图看起来不是" + what + "，请重新拍摄或选择。"
        if model_reason:
            text = text + "（" + model_reason + "）"
        return text


def build_checker(moma=None, model: str = "", role: str = "sub"):
    """按"当前有没有可用的多模态模型"选核验器。

    没配模型时直接给 `StubChecker`——省掉"先把整张图 base64、再发现走不通"的浪费。
    """
    if moma is None:
        return StubChecker()
    try:
        live = moma.role_live(role)
    except Exception:
        live = False
    return VisionChecker(moma, model=model, role=role) if live else StubChecker()


def check_file(spec: Dict[str, Any], filename: str, content: bytes, slot: str = "",
               checker=None) -> Dict[str, str]:
    """核验单张文件：先形式校验，再交给核验器做内容核验。

    返回 `{result, status, reason}`（`result` 为 `通过 / 需补正 / 不通过`）。
    """
    rejected = form_check(spec, filename, content)
    if rejected:
        return rejected
    return (checker or StubChecker()).check(spec, filename, content, slot)


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
