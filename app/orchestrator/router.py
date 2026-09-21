"""意图路由：把用户输入路由到对应 Agent。"""

INTENT_KEYWORDS = {
    "consult": ["是什么", "怎么", "流程", "材料", "需要", "条件", "多少", "咨询", "要办", "办什么"],
    "apply": ["开", "办", "注册", "申请", "我要", "想开", "想办", "创业"],
    "query": ["进度", "查询", "到哪", "状态", "办好没"],
}


def route_intent(text: str) -> str:
    for intent, words in INTENT_KEYWORDS.items():
        for w in words:
            if w in text:
                return intent
    return "consult"
