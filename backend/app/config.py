import os
import platform
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

if platform.system() == "Darwin" and os.environ.get("KMP_DUPLICATE_LIB_OK") is None:
    os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

# HuggingFace 镜像源（国内加速下载 Embedding 模型）
if os.environ.get("HF_ENDPOINT") is None:
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    app_secret: str = os.getenv("APP_SECRET", "campus-qa-local-development-secret")
    database_path: Path = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "campus_qa.db")))
    upload_dir: Path = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "data" / "uploads")))
    data_dir: Path = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
    knowledge_base_dir: Path = Path(os.getenv("KNOWLEDGE_BASE_DIR", str(BASE_DIR.parent / "knowledge-base")))
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
    frontend_origins: list[str] = field(default_factory=lambda: sorted({
        origin.strip() for origin in os.getenv(
            "FRONTEND_ORIGINS",
            os.getenv("FRONTEND_ORIGIN", "http://localhost:5173"),
        ).split(",") if origin.strip()
    } | {"http://localhost:5173", "http://localhost:8080", "http://localhost:8081"}))

    # LLM (DeepSeek / OpenAI-compatible)
    llm_api_key: str = os.getenv("LLM_API_KEY", os.getenv("DASHSCOPE_API_KEY", ""))
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    llm_model: str = os.getenv("LLM_MODEL", "deepseek-chat")
    llm_timeout_seconds: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "45"))
    llm_max_retries: int = int(os.getenv("LLM_MAX_RETRIES", "2"))

    # Embedding
    dashscope_api_key: str = os.getenv("DASHSCOPE_API_KEY", "")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")
    use_local_embedding: bool = os.getenv("DASHSCOPE_API_KEY", "") == ""
    local_embedding_model: str = os.getenv("LOCAL_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
    allow_model_download: bool = os.getenv("ALLOW_MODEL_DOWNLOAD", "false").lower() == "true"
    embedding_batch_size: int = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))

    # RAG
    top_k: int = int(os.getenv("TOP_K", "5"))
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "500"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "50"))
    retrieval_strategy: str = os.getenv("RETRIEVAL_STRATEGY", "hybrid")
    similarity_threshold: float = float(os.getenv("SIMILARITY_THRESHOLD", "0.7"))
    cache_enabled: bool = os.getenv("CACHE_ENABLED", "true").lower() == "true"
    cache_ttl_seconds: int = int(os.getenv("CACHE_TTL_SECONDS", "3600"))
    enable_query_rewrite: bool = os.getenv("ENABLE_QUERY_REWRITE", "true").lower() == "true"
    enable_self_rag: bool = os.getenv("ENABLE_SELF_RAG", "false").lower() == "true"
    enable_context_compression: bool = os.getenv("ENABLE_CONTEXT_COMPRESSION", "true").lower() == "true"
    enable_reranker: bool = os.getenv("ENABLE_RERANKER", "false").lower() == "true"
    enable_auto_strategy: bool = os.getenv("ENABLE_AUTO_STRATEGY", "false").lower() == "true"

    # Advanced chunking strategies
    semantic_chunking_enabled: bool = os.getenv("SEMANTIC_CHUNKING_ENABLED", "false").lower() == "true"
    parent_child_enabled: bool = os.getenv("PARENT_CHILD_ENABLED", "false").lower() == "true"
    child_chunk_size: int = int(os.getenv("CHILD_CHUNK_SIZE", "300"))
    parent_chunk_size: int = int(os.getenv("PARENT_CHUNK_SIZE", "1000"))
    semantic_threshold: float = float(os.getenv("SEMANTIC_THRESHOLD", "0.6"))

    # Rate limit
    rate_limit_enabled: bool = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "100"))

    token_minutes: int = 60 * 24
    captcha_required: bool = os.getenv("CAPTCHA_REQUIRED", "true").lower() == "true"
    captcha_ttl_seconds: int = int(os.getenv("CAPTCHA_TTL_SECONDS", "300"))
    # Day 4 requirement: PDF / Word / TXT up to 50 MB.  The limit is shared
    # by the API and the streaming file writer so oversized bodies are stopped
    # before they are held completely in memory.
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
    max_preview_chars: int = int(os.getenv("MAX_PREVIEW_CHARS", "20000"))


settings = Settings()
