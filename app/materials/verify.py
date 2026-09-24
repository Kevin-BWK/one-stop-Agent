"""单张材料的核验规则与**可插拔的内容核验器**（见 `docs/09`）。

分两级：

1. **形式校验**（`form_check`）：纯规则、本地瞬时完成——扩展名、空文件、体积上限。
   不合格直接 `不通过`（文件收不下，前端要重选）；
2. **内容核验**（核验器）：这份材料的照片**是不是真是那份材料**、清不清晰。

## 分工：简单的本地判，只有必须语义判断的才交给大模型

| 判什么 | 谁判 | 为什么 |
| --- | --- | --- |
| 格式 / 空文件 / 体积上限 | 本地规则（`form_check`） | 硬规则，与内容无关；格式不对的文件连图都解不出 |
| 图片体积过小 / **像素分辨率过低** | 本地规则（`StubChecker`，读文件头） | **客观事实**，读文件头就能得到，没有语义成分 |
| **这张图到底是不是这份材料** | **多模态模型**（`VisionChecker`） | 只能是语义判断，规则写不出来 |
| 清晰度 / 反光 / 裁边 / 屏幕翻拍 | 多模态模型 | 同上（启发式规则误判率高，交给模型更准） |

`VisionChecker` 是"本地规则 + 语义模型"的组合：**本地规则永远先跑，判出问题就直接返回，
不花这一次模型调用**；本地判不出来、又必须语义判断时，才真的问模型。

**降级策略（很重要）**：模型不可用 / 超时 / 返回无法解析 → 一律**回落到本地规则层的结论**。
材料核验是办事链路的必经环节，不能因为模型故障就让群众交不上材料。

判定语义：

- `通过`   —— 收下，该槽位占位；
- `需补正` —— 收下但标记需补正，用户可原地重传（**"内容不对/看不清"属于这一类**）；
- `不通过` —— 文件根本收不下（格式 / 体积），前端要重选。

## 文案规范（每条"不能收 / 要重传"的说明都必须回答三件事）

办事人看到提示后要能**直接动手**，所以每条说明都写成"问题 + 怎么改"：

1. **是什么问题**——具体到能自证（"这个文件 18.4MB"、"这张图只有 3KB"、"画面里是一只猫"）；
2. **为什么不行**——对照的规矩（"超过单张 10MB 上限"、"不像身份证正面"）；
3. **怎么改**——可执行的动作（"压缩后再传"、"平放拍，四角进画面，别开闪光灯"）。

"怎么改"的来源，按优先级：模型给的 `fix` > 场景配置的 `fix_hint` > 通用兜底。
形式校验**不走模型**：格式/体积是硬规则，与内容无关，而且格式不对根本解不出图，
没必要花一次模型调用去说"你的文件太大了"——本地把判据说具体就够。
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

# 本地规则能判的两条硬伤：都是客观事实，读文件头就够，不该花模型调用
MIN_IMAGE_BYTES = 5 * 1024          # 低于这个体积，多半是缩略图 / 截图
MIN_IMAGE_EDGE = 480                # 短边低于这个像素数，放大后看不清字
IMAGE_EXTS = ("jpg", "jpeg", "png")

# 超过这个体积就不送模型：base64 后请求体会再膨胀约 1/3，得不偿失，回落桩规则
VISION_MAX_BYTES = 2 * 1024 * 1024

_MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}
_JSON_BLOCK = re.compile(r"\{.*\}", re.S)
_LONG_DIGITS = re.compile(r"\d{8,}")
_TRUE_WORDS = ("true", "yes", "ok", "1", "是", "通过", "合规", "符合")


def _passed() -> Dict[str, str]:
    return {"result": RESULT_PASS, "status": FILE_PASSED, "reason": ""}


def _need_fix(reason: str) -> Dict[str, str]:
    return {"result": RESULT_NEED_FIX, "status": FILE_NEED_FIX, "reason": reason}


def _reject(reason: str) -> Dict[str, str]:
    return {"result": RESULT_REJECT, "status": "", "reason": reason}


def human_size(num: int) -> str:
    """字节数说成人话：18432000 -> `17.6MB`，820 -> `820B`。"""
    if num >= 1024 * 1024:
        text = "%.1f" % (num / 1048576.0)
        return (text[:-2] if text.endswith(".0") else text) + "MB"
    if num >= 1024:
        return str(int(round(num / 1024.0))) + "KB"
    return str(int(num)) + "B"


def image_size(content: bytes) -> Optional[tuple]:
    """零依赖读图片像素尺寸（只认 jpg / png），返回 `(宽, 高)`；读不出返回 `None`。

    读不出时调用方**不做分辨率判断**——宁可少判一条，也不能把一张好图误判成"看不清"。
    这也包括 HEIC 等本函数不认的格式（`accept` 里目前没有，真加了再补解析）。
    """
    if content[:8] == b"\x89PNG\r\n\x1a\n":
        if len(content) >= 24:
            return (int.from_bytes(content[16:20], "big"),
                    int.from_bytes(content[20:24], "big"))
        return None

    if content[:2] == b"\xff\xd8":
        index = 2
        total = len(content)
        while index + 9 <= total:
            if content[index] != 0xFF:
                index += 1
                continue
            marker = content[index + 1]
            # 无载荷的标记：SOI、TEM、RSTn
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                index += 2
                continue
            seg_len = int.from_bytes(content[index + 2:index + 4], "big")
            if seg_len < 2:
                return None
            # SOFn（排除 DHT=C4、JPG=C8、DAC=CC）里存着尺寸
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                return (int.from_bytes(content[index + 7:index + 9], "big"),
                        int.from_bytes(content[index + 5:index + 7], "big"))
            index += 2 + seg_len
        return None

    return None


def material_label(spec: Dict[str, Any], slot: str = "") -> str:
    """给用户看的指代：「法定代表人身份证」的「正面」。"""
    label = "「" + str(spec.get("name", "")) + "」"
    return label + "的「" + slot + "」" if slot else label


def default_fix(spec: Dict[str, Any], slot: str = "") -> str:
    """"怎么改"的兜底说法。

    场景条目可以用 `fix_hint` 写得更贴切（如"拍产权证的地址页与盖章页"），
    里面出现 `{slot}` 会被替换成具体槽位，例如"把身份证「{slot}」平放再拍"。
    """
    hint = str(spec.get("fix_hint") or "").strip()
    if hint:
        return hint.replace("{slot}", slot or "")
    return "请重新拍一张" + material_label(spec, slot) + "：四角都进画面，光线充足，不要反光或遮挡。"


def clean_text(text: Any, limit: int = 120) -> str:
    """把模型给的一句话收拾成能直接给用户看的样子。

    - 压平换行与多余空白（前端按一段话展示，换行会撑乱布局）；
    - 屏蔽 8 位以上连续数字：证件号 / 卡号不该被写进落盘的材料记录；
    - 限长，避免模型长篇大论把提示撑爆。
    """
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    text = _LONG_DIGITS.sub("……", text)
    text = text.strip(" 。,，；;")
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


def form_check(spec: Dict[str, Any], filename: str, content: bytes) -> Optional[Dict[str, str]]:
    """形式校验：合格返回 `None`，不合格返回拒绝结果（说清"多大/什么格式 + 怎么改"）。"""
    accept = [item.lower() for item in (spec.get("accept") or DEFAULT_ACCEPT)]
    ext = ext_of(filename)

    if ext not in accept:
        got = ("." + ext) if ext else "没有扩展名"
        return _reject(
            "你选的文件是 " + got + " 格式，这里只收 " + "、".join(accept) + "。"
            + "请用「另存为 / 导出」转成 " + accept[0] + " 后再传。"
        )
    if not content:
        return _reject(
            "这个文件是空的（0 字节），多半是没选对文件或上传中断了。"
            "请重新选择，或者直接重新拍一张。"
        )
    if len(content) > DEFAULT_MAX_FILE_BYTES:
        return _reject(
            "这个文件 " + human_size(len(content)) + "，超过了单张 "
            + human_size(DEFAULT_MAX_FILE_BYTES) + " 的上限。"
            + "请压缩后再传：手机上拍照可以选小一档的分辨率，或先用相册「裁剪」去掉多余部分。"
        )
    return None


class StubChecker:
    """本地规则核验：**能用本地规则判的一律本地判**，不花模型调用。

    覆盖两类"客观硬伤"——读文件头就能得出，没有语义成分：

    - 图片体积过小（多半是缩略图 / 截图，不是原图）；
    - 图片分辨率过低（放大后看不清字）。

    没配多模态模型时，它单独承担内容核验；配了模型时，它仍是**前置层**先跑
    （见 `VisionChecker`），只有它判不出来、且必须语义判断的部分才交给模型。
    """

    def check(self, spec: Dict[str, Any], filename: str, content: bytes,
              slot: str = "") -> Dict[str, str]:
        if ext_of(filename) not in IMAGE_EXTS:
            return _passed()

        if len(content) < MIN_IMAGE_BYTES:
            return _need_fix(
                "这张图只有 " + human_size(len(content)) + "，太小了看不清内容"
                "（多半是缩略图或截图，不是原图）。" + default_fix(spec, slot)
            )

        size = image_size(content)
        if size and min(size) < MIN_IMAGE_EDGE:
            return _need_fix(
                "这张图只有 " + str(size[0]) + "×" + str(size[1]) + " 像素，放大后字会糊"
                "（像是截图，或拍照时被压缩过）。" + default_fix(spec, slot)
            )
        return _passed()


def data_url(ext: str, content: bytes) -> str:
    """把图片编码成 `data:` URL（零依赖；真实生产可改为上传对象存储后给外链）。"""
    mime = _MIME.get(ext, "image/jpeg")
    return "data:" + mime + ";base64," + base64.b64encode(content).decode("ascii")


def parse_verdict(reply: Any) -> Optional[Dict[str, Any]]:
    """从模型回复里取出 `{ok, problem, fix}`；取不到返回 `None`（调用方据此回落桩规则）。

    模型常把 JSON 包在 ```json 代码块里、或前后带些解释文字，所以先用正则抓第一个
    对象再严格解析——**宁可回落桩规则，也不要把半截结果当结论**。
    早期契约只回 `reason`，这里也认，当作 `problem` 用。
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
    return {
        "ok": bool(ok),
        "problem": clean_text(data.get("problem") or data.get("reason")),
        "fix": clean_text(data.get("fix")),
    }


class VisionChecker:
    """本地规则 + 语义模型：**简单的本地判，只有必须语义判断的才问模型**。

    执行顺序（见模块开头的分工表）：

    1. 本地规则层先跑（`StubChecker`）：判出问题就**直接返回，一次模型调用都不花**；
    2. 没有视觉通道的（非图片 / 图太大）也到此为止，本地结论就是最终结论；
    3. 只剩一个本地判不了、且必须语义判断的问题——**这张图到底是不是这份材料**——才调模型；
    4. 模型不可用 / 超时 / 返回无法解析 → 回落第 1 步的结论（办事链路不能卡在模型上）。
    """

    def __init__(self, moma, model: str = "", role: str = "sub", local=None):
        self.moma = moma
        self.model = model or "qwen-vl"
        self.role = role
        # 本地规则层：既是"能判就不问模型"的前置过滤，也是模型不可用时的兜底
        self.local = local or StubChecker()

    def check(self, spec: Dict[str, Any], filename: str, content: bytes,
              slot: str = "") -> Dict[str, str]:
        # 1) 本地规则先跑：能判的一律不花模型调用
        local = self.local.check(spec, filename, content, slot)
        if local["result"] != RESULT_PASS:
            return local

        # 2) 没有视觉通道（非图片 / 图太大）：本地结论就是最终结论
        ext = ext_of(filename)
        if ext not in IMAGE_EXTS or len(content) > VISION_MAX_BYTES:
            return local

        # 3) 剩下的才是必须语义判断的：这张图到底是不是这份材料
        try:
            reply = self.moma.complete(
                self.model,
                self.messages(spec, slot, ext, content),
                fallback="",        # 桩模式只会拿到空串 -> 解析失败 -> 回落本地规则
                role=self.role,
            )
        except Exception:
            # 模型故障不该卡住办事：交材料这条链路必须能走下去
            return local

        verdict = parse_verdict(reply)
        if verdict is None:
            return local
        if verdict["ok"]:
            return _passed()
        return _need_fix(self.describe_rejection(spec, slot, verdict))

    @staticmethod
    def messages(spec: Dict[str, Any], slot: str, ext: str, content: bytes) -> List[Dict[str, Any]]:
        """构造多模态消息（OpenAI 兼容：`content` 为数组，含文本与图片 data URL）。"""
        label = material_label(spec, slot)
        system = (
            "你是政务办事材料审核助手，判断用户上传的图片是不是一张合规的办事材料照片。"
            "看不清、明显是别的物件、是屏幕翻拍或截图、被严重遮挡——都算不合规。"
            "只输出一个 JSON 对象："
            "{\"ok\": true 或 false, \"problem\": \"看到了什么问题\", \"fix\": \"拍照的人该怎么改\"}。"
            "ok 为 true 时 problem 与 fix 留空串。"
            "problem 与 fix 各写一句话、用日常口语、说具体："
            "problem 说清画面里实际是什么、缺了什么（别抄证件号码，别出现「模型」「识别」这类词），"
            "fix 写成可以直接照做的动作。"
            "不要输出 JSON 以外的任何内容。"
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
    def describe_rejection(spec: Dict[str, Any], slot: str, verdict: Dict[str, Any]) -> str:
        """把模型的判断说成办事人看得懂、能照着改的一段话。

        格式是「问题 + 怎么改」：问题尽量用模型的原话（更具体），怎么改优先用模型给的
        动作，模型没给就用场景的 `fix_hint`，再兜底成通用说法。
        """
        label = material_label(spec, slot)
        problem = verdict.get("problem") or ""
        head = "这张图不像" + label + ("：" + problem if problem else "") + "。"
        text = head + (verdict.get("fix") or default_fix(spec, slot))
        # clean_text 会把模型话尾的标点去掉，这里补回来，保证整段是一个完整的句子
        return text if text.endswith("。") else text + "。"


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
