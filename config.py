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

# 单次回复上限：防止模型陷入工具标签死循环时无限输出
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "2000"))

# 聊天模型统一入口：优先直连 DeepSeek；没有 DeepSeek key 时用 Vercel AI Gateway
GATEWAY_CHAT_MODEL = os.environ.get("GATEWAY_CHAT_MODEL", "google/gemini-4-hydrogen").strip()
GATEWAY_VISION_MODEL = (os.environ.get("GATEWAY_VISION_MODEL", "").strip()
                        or GATEWAY_CHAT_MODEL)

# 语音转写配置(Phase 2):whisper-1,走 Vercel AI Gateway 或直连 OpenAI
AI_GATEWAY_API_KEY = os.environ.get("AI_GATEWAY_API_KEY", "").strip()
AI_GATEWAY_BASE_URL = os.environ.get(
    "AI_GATEWAY_BASE_URL", "https://ai-gateway.vercel.sh/v1"
).rstrip("/")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
# 留空则按上面的 provider 自动选:Gateway = openai/whisper-1,直连 = whisper-1
TRANSCRIBE_MODEL = os.environ.get("TRANSCRIBE_MODEL", "").strip()
TRANSCRIBE_LANGUAGE = os.environ.get("TRANSCRIBE_LANGUAGE", "").strip()
TRANSCRIBE_PROMPT = os.environ.get(
    "TRANSCRIBE_PROMPT",
    "以下是影视制作相关的内容,术语包括:分镜、场次、机位、景别、画面、rundown、剧本、后期、调色、收音、打灯。",
).strip()

# RAG 配置
KNOWLEDGE_FILE = BASE_DIR / "knowledge" / "knowledge.json"
TOP_K = int(os.environ.get("RAG_TOP_K", "3"))
MIN_SCORE = float(os.environ.get("RAG_MIN_SCORE", "0.0"))
# dense: 用 sentence-transformers 向量检索;auto: 装了就用,否则回退 BM25
EMBEDDING_MODE = os.environ.get("EMBEDDING_MODE", "auto").strip().lower()

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))

# Phase 3 会话存储(chat storage):会话历史落盘目录(每个会话一个 JSON 文件)
CONVERSATIONS_DIR = Path(
    os.environ.get("CONVERSATIONS_DIR", str(BASE_DIR / "data" / "conversations"))
).expanduser()


def llm_settings(api_key: str = None):
    """返回 (key, base_url, model, provider)。

    优先级：调用方传入的 key > 直连 DeepSeek > Vercel AI Gateway。
    """
    key = (api_key or "").strip()
    if key:
        return key, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, "direct"
    if DEEPSEEK_API_KEY:
        return DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, "deepseek"
    if AI_GATEWAY_API_KEY:
        return AI_GATEWAY_API_KEY, AI_GATEWAY_BASE_URL, GATEWAY_CHAT_MODEL, "gateway"
    return "", DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, "offline"
