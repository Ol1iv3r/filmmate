"""全局配置。优先读环境变量,其次读 .env 文件。"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

def _load_dotenv():
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

_load_dotenv()

# 大模型配置
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

# RAG 配置
KNOWLEDGE_FILE = BASE_DIR / "knowledge" / "knowledge.json"
TOP_K = int(os.environ.get("RAG_TOP_K", "3"))
MIN_SCORE = float(os.environ.get("RAG_MIN_SCORE", "0.0"))
# dense: 用 sentence-transformers 向量检索;auto: 装了就用,否则回退 BM25
EMBEDDING_MODE = os.environ.get("EMBEDDING_MODE", "auto").strip().lower()

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
