"""咨询 Agent：用**自然语言**解答群众关于流程、材料、事项的问题。

桩实现：按问题关键词，从场景配置里组织人话回答（不出现 JSON / 内部 id / 模型名）。
真实实现：把问题 + 场景上下文交给 MoMA 对话模型；对外接口不变。
"""
from .base import BaseAgent

MATERIAL_WORDS = ("材料", "证件", "带什么", "准备", "要交")
PROCESS_WORDS = ("流程", "步骤", "多久", "多长时间", "几天", "怎么办")
ITEM_WORDS = ("办什么", "要办", "哪些事", "事项", "需要办", "涉及")
APPLY_WORDS = ("我想", "我要", "想开", "想办", "注册", "申请", "开一家", "开办")


class ConsultAgent(BaseAgent):
    name = "consult"

    def answer(self, question, scenario):
        reply = self._compose(question or "", scenario)
        self.context.add_history("user", question)
        self.context.add_history("assistant", reply)
        return reply

    # ---------- 内部 ----------

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
        base = scenario.get("base_materials") or []
        lines = ["这件事的基础材料有 " + str(len(base)) + " 份：" + "、".join(base) + "。"]
        lines.append("另外会根据您的实际情况增加材料，例如：")
        for rule in scenario.get("condition_rules", []):
            added = rule.get("add_materials") or []
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
