"""咨询 Agent：解答群众关于办事流程、材料、事项的问题。

两条路径，对外接口一致：

1. **优先走 MoMA**（真实模式）：把「问题 + 场景上下文」交给对话模型；
2. **本地兜底**（未配置 MoMA、或模型调用失败）：用关键词规则组织**固定人话**回答，
   保证零依赖 Demo 与离线单测仍然可用。

两条路径都遵守 `docs/08` 的文案规范：不出现 JSON 字面量、内部事项 id、字段 key、模型名。

回答**可以带办事指南依据**：传入 `knowledge` 时先按问题检索相关片段（见
`app/knowledge/retriever.py`），命中就作为模型作答的依据、也附在离线兜底回答后面。
检索是增强项——没传知识库或没命中时，行为与之前完全一致。
"""
from ..knowledge.retriever import format_chunks
from ..materials.spec import material_names
from .base import BaseAgent

MATERIAL_WORDS = ("材料", "证件", "带什么", "准备", "要交")
PROCESS_WORDS = ("流程", "步骤", "多久", "多长时间", "几天", "怎么办")
ITEM_WORDS = ("办什么", "要办", "哪些事", "事项", "需要办", "涉及")
APPLY_WORDS = ("我想", "我要", "想开", "想办", "注册", "申请", "开一家", "开办")


class ConsultAgent(BaseAgent):
    name = "consult"

    # 带进对话上下文的最大历史条数（约 3 轮问答）。
    # 不设上限会让长会话把请求撑爆，也会让模型被早期无关内容带偏。
    MAX_HISTORY = 6

    # 每次咨询带进办事指南的最大片段数
    TOP_K = 3

    # 检索 query 里最多拼入几轮历史**用户**提问（约 1 轮），避免把当前问题淹没
    SEARCH_HISTORY = 2
    # 单条历史在检索 query 里的最大字符数（长句只留开头，够定位话题即可）
    SEARCH_HISTORY_CHARS = 120

    def answer(self, question, scenario, knowledge=None):
        """作答。传入 `knowledge` 时会先检索办事指南作为依据。"""
        model = self.model_for()
        chunks = self._guide_chunks(knowledge, scenario, question)
        reply = self.moma.complete(
            model,
            self._messages(question, scenario, chunks),
            fallback=self._local_reply(question, scenario, chunks),  # 离线 / 失败时的人话兜底
            context=self.context,
            role=self.role,
        )
        self.context.add_history("user", question)
        self.context.add_history("assistant", reply)
        return reply

    # ---------- 办事指南依据 ----------

    def _guide_chunks(self, knowledge, scenario, question):
        """按问题检索办事指南片段；没传知识库、或没命中，都返回空列表。"""
        if knowledge is None:
            return []
        try:
            return knowledge.search(scenario.get("id", ""), self._search_query(question),
                                    top_k=self.TOP_K)
        except Exception:
            # 检索是增强项：它出问题不该让"咨询"整个失败
            return []

    def _search_query(self, question):
        """把最近几轮**用户提问**拼进检索 query（只影响检索，不改发给模型的消息）。

        用户常问省略句（"那第二个呢""这个要多少钱"），只拿当前这句去检索会跑偏；
        带上上文才定位得到话题。发给模型的消息仍用原问题——多轮上下文由
        `context.history()` 在 `_messages()` 里负责，两者互不干扰。
        """
        text = (question or "").strip()
        if self.context is None:
            return text
        try:
            history = self.context.history()
        except Exception:
            return text
        recent = []
        for item in history:
            if item.get("role") != "user":
                continue
            content = str(item.get("content") or "").strip()
            if content:
                recent.append(content[:self.SEARCH_HISTORY_CHARS])
        if not recent:
            return text
        return " ".join(recent[-self.SEARCH_HISTORY:] + [text])

    # ---------- 给模型的消息 ----------

    @staticmethod
    def _item_text(scenario):
        return "、".join(
            v["name"] + "（" + v["department"] + "）" for v in scenario["items"].values()
        )

    def _messages(self, question, scenario, chunks=()):
        # 材料在场景配置里存的是 id，喂给模型前必须转成中文名（见 docs/08 文案规范）
        materials = "、".join(material_names(scenario, scenario.get("base_materials") or []))
        system = (
            "你是“一件事·一次办”政务办事咨询助手，回答要简洁、准确、口语化，"
            "只围绕当前办理事项作答；不要输出 JSON、内部编号或模型名。"
            "当前事项：" + scenario.get("name", "") + "。"
            "办理事项：" + self._item_text(scenario) + "。"
            "基础材料：" + (materials or "以办事指南为准") + "。"
        )
        if chunks:
            # 检索到的指南片段作为作答依据；提醒它别把片段原样倒出来
            system += ("\n\n【办事指南节选（作答依据，请用自己的话回答，不要照抄）】\n"
                       + format_chunks(chunks))
        messages = [{"role": "system", "content": system}]
        # 多轮上下文：带上本会话之前的问答，用户才能说"那第二个呢"这种省略句。
        # 当前问题此时还没写进 history（answer() 在拿到回复后才记），所以不会重复。
        history = self.context.history() if self.context is not None else []
        messages += history[-self.MAX_HISTORY:]
        messages.append({"role": "user", "content": question or ""})
        return messages

    # ---------- 本地兜底：离线或模型失败时，按问题给固定人话 ----------

    def _local_reply(self, question, scenario, chunks=()):
        reply = self._compose(question or "", scenario)
        if chunks:
            # 让离线兜底也带上检索依据，否则"接了知识库"在离线时看不出任何变化
            reply += "\n\n（来自办事指南）\n" + format_chunks(chunks)
        return reply

    def _compose(self, question, scenario):
        text = question or ""
        if self._hit(text, MATERIAL_WORDS):
            return self._about_materials(scenario)
        if self._hit(text, PROCESS_WORDS):
            return self._about_process(scenario)
        if self._hit(text, ITEM_WORDS):
            return self._about_items(scenario)
        if self._hit(text, APPLY_WORDS):
            return (
                "好的，我来帮您办「" + self._short_name(scenario) + "」。"
                "办理过程中您随时可以问我：需要什么材料、流程是怎样的、要满足什么条件。"
            )
        return self._overview(scenario)

    @staticmethod
    def _short_name(scenario):
        return (scenario.get("name") or "这件事").replace("一件事", "")

    @staticmethod
    def _hit(text, words):
        return any(word in text for word in words)

    def _about_materials(self, scenario):
        base = material_names(scenario, scenario.get("base_materials") or [])
        lines = ["这件事的基础材料有 " + str(len(base)) + " 份：" + "、".join(base) + "。"]
        lines.append("另外会根据您的实际情况增加材料，例如：")
        for rule in scenario.get("condition_rules", []):
            added = material_names(scenario, rule.get("add_materials") or [])
            if added and rule.get("note"):
                lines.append("· " + rule["note"] + " → 需要「" + "、".join(added) + "」")
        lines.append("您先填写申请信息，我会按您的情况给出最终的材料清单。")
        return "\n".join(lines)

    def _about_process(self, scenario):
        base = scenario.get("base_items") or []
        names = "、".join(self._item_name(scenario, item) for item in base)
        return (
            "办理流程是这样的：\n"
            "1. 您告诉我基本情况（我会逐项跟您确认）；\n"
            "2. 我判断您需要办哪些事、要交哪些材料；\n"
            "3. 材料齐了统一提交，各部门并联办理，不用您挨个跑；\n"
            "4. 办好后出件，您可以随时查进度。\n"
            "您这件事的基础事项是：" + names + "，具体还要看您的实际情况。"
        )

    def _about_items(self, scenario):
        items = scenario.get("items", {})
        names = "、".join(
            item["name"] + "（" + item.get("department", "") + "）" for item in items.values()
        )
        return (
            "这件事可能涉及：" + names + "。\n"
            "具体要办哪些，取决于您的经营情况——比如面积多大、有没有油烟、是否设招牌，我会帮您判断。"
        )

    def _overview(self, scenario):
        guide = scenario.get("guide", "")
        return (
            "我是「一件事·一次办」的办事助手，负责帮您把「" + self._short_name(scenario) + "」一次办好。"
            + (guide if guide else "")
            + " 您可以直接告诉我您想办什么，或者问我需要什么材料、办理流程是怎样的。"
        )

    def _item_name(self, scenario, item_id):
        meta = scenario.get("items", {}).get(item_id)
        return meta["name"] if meta else item_id
