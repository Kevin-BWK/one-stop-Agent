"""知识库（桩）：从本地 markdown 加载办事指南，按场景检索。"""
from pathlib import Path


class KnowledgeBase:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self._docs = {}
        for p in self.data_dir.glob("*.md"):
            key = p.stem.replace("_guide", "")
            self._docs[key] = p.read_text(encoding="utf-8")

    def retrieve(self, scenario_id: str, query: str = "") -> str:
        # 真实实现：向量检索 / RAG。此处直接返回整篇指南。
        return self._docs.get(scenario_id, "未找到该场景办事指南。")
