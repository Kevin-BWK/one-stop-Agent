"""意图路由：把用户输入路由到对应 Agent。"""

INTENT_KEYWORDS = {
    "consult": ["是什么", "怎么", "流程", "材料", "需要", "条件", "多少", "咨询", "要办", "办什么"],
    "apply": ["开", "办", "注册", "申请", "我要", "想开", "想办", "创业"],
    "query": ["进度", "查询", "到哪", "状态", "办好没"],
}


def route_intent(text: str) -> str:
    # 优先级：进度查询 > 咨询 > 办事；避免“办理进度”被“办”误路由到办事
    for intent in ("query", "consult", "apply"):
        for w in INTENT_KEYWORDS[intent]:
            if w in text:
                return intent
    return "consult"