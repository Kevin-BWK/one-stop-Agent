"""全局路径与配置。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = ROOT / "scenarios"
KNOWLEDGE_DIR = ROOT / "data" / "knowledge"
