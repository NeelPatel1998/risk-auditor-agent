import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_ROOT = Path(__file__).resolve().parent.parent

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek/deepseek-chat-v3-0324")
# Cap completion tokens on every chat request (stream + non-stream). Omitting max_tokens lets OpenRouter
# use a large model default (often 8k-class), which can trigger HTTP 402 on low credits.
LLM_MAX_TOKENS = max(1, int(os.getenv("LLM_MAX_TOKENS", "4096")))
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "qwen/qwen3-embedding-8b")

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))

UPLOAD_DIR = os.getenv("UPLOAD_DIR", str(_ROOT / "data" / "uploads"))
CHROMA_DIR = os.getenv("CHROMA_DIR", str(_ROOT / "data" / "chroma"))
CHECKPOINT_DB = os.getenv("CHECKPOINT_DB", str(_ROOT / "data" / "checkpoints.db"))

CORS_ORIGIN = os.getenv("CORS_ORIGIN", "http://localhost:5173")


def cors_allow_origins() -> list[str]:
    """Browser dev URLs that commonly hit the API (localhost vs 127.0.0.1 are different origins)."""
    extras = os.getenv("CORS_ORIGINS", "")
    items = [
        CORS_ORIGIN,
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ]
    if extras.strip():
        items.extend(x.strip() for x in extras.split(",") if x.strip())
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# Chroma L2 distance on normalized embedding space; tune if retrieval too strict/loose
RETRIEVAL_MAX_DISTANCE = float(os.getenv("RETRIEVAL_MAX_DISTANCE", "2.5"))

# Embed many chunks per OpenRouter request; too large a batch can 413/timeout (500 from API)
EMBED_BATCH_SIZE = max(1, int(os.getenv("EMBED_BATCH_SIZE", "32")))

# If true, wipe the Chroma collection (and uploaded PDF files on disk) before each new upload
CLEAR_CHROMA_ON_UPLOAD = os.getenv("CLEAR_CHROMA_ON_UPLOAD", "").lower() in ("1", "true", "yes")

# Microservices: "local" = in-process vector_store; "remote" = HTTP to Document service
RETRIEVAL_MODE = os.getenv("RETRIEVAL_MODE", "local").strip().lower()
DOCUMENT_SERVICE_URL = os.getenv("DOCUMENT_SERVICE_URL", "").strip()
INTERNAL_API_TOKEN = os.getenv("INTERNAL_API_TOKEN", "").strip()
