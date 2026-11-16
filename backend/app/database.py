from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from .config import settings

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'STUDENT' CHECK(role IN ('STUDENT','ADMIN')),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    filename TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PROCESSING' CHECK(status IN ('PROCESSING','READY','ERROR')),
    chunk_count INTEGER NOT NULL DEFAULT 0,
    source_url TEXT, category TEXT, original_path TEXT, error TEXT,
    uploaded_by INTEGER NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    processing_step TEXT NOT NULL DEFAULT 'UPLOADED',
    content_hash TEXT,
    content_override TEXT,
    content_edited_at TEXT,
    preview_cache TEXT,
    preview_cache_key TEXT,
    preview_cache_truncated INTEGER NOT NULL DEFAULT 0,
    preview_cached_at TEXT,
    preview_cache_error TEXT,
    review_status TEXT NOT NULL DEFAULT 'APPROVED' CHECK(review_status IN ('PENDING','APPROVED','REJECTED')),
    review_note TEXT, reviewed_by INTEGER, reviewed_at TEXT, uploader_key TEXT,
    FOREIGN KEY(uploaded_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL, title TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('USER','ASSISTANT')),
    content TEXT NOT NULL,
    sources TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS system_config (
    key TEXT PRIMARY KEY, value TEXT NOT NULL, description TEXT, updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, endpoint TEXT NOT NULL, method TEXT NOT NULL,
    status_code INTEGER NOT NULL, duration_ms INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rag_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL, expected_answer TEXT, actual_answer TEXT NOT NULL,
    sources_json TEXT, relevance_score REAL, faithfulness_score REAL,
    latency_ms INTEGER, created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kb_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_tag TEXT NOT NULL, document_count INTEGER, chunk_count INTEGER,
    build_duration_ms INTEGER, status TEXT NOT NULL DEFAULT 'building',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quick_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL, category TEXT,
    sort_order INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    page_number INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE(document_id, chunk_index),
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_document_chunks_document ON document_chunks(document_id);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or settings.database_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_database(path: Path | None = None) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        # Lightweight migrations for databases created by earlier course days.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(documents)")}
        if "processing_step" not in columns:
            conn.execute("ALTER TABLE documents ADD COLUMN processing_step TEXT NOT NULL DEFAULT 'UPLOADED'")
        if "content_hash" not in columns:
            conn.execute("ALTER TABLE documents ADD COLUMN content_hash TEXT")
        if "review_status" not in columns:
            conn.execute("ALTER TABLE documents ADD COLUMN review_status TEXT NOT NULL DEFAULT 'APPROVED'")
        if "review_note" not in columns:
            conn.execute("ALTER TABLE documents ADD COLUMN review_note TEXT")
        if "reviewed_by" not in columns:
            conn.execute("ALTER TABLE documents ADD COLUMN reviewed_by INTEGER")
        if "reviewed_at" not in columns:
            conn.execute("ALTER TABLE documents ADD COLUMN reviewed_at TEXT")
        if "uploader_key" not in columns:
            conn.execute("ALTER TABLE documents ADD COLUMN uploader_key TEXT")
            conn.execute("UPDATE documents SET uploader_key='user:' || uploaded_by WHERE uploader_key IS NULL")
        if "content_override" not in columns:
            conn.execute("ALTER TABLE documents ADD COLUMN content_override TEXT")
        if "content_edited_at" not in columns:
            conn.execute("ALTER TABLE documents ADD COLUMN content_edited_at TEXT")
        if "preview_cache" not in columns:
            conn.execute("ALTER TABLE documents ADD COLUMN preview_cache TEXT")
        if "preview_cache_key" not in columns:
            conn.execute("ALTER TABLE documents ADD COLUMN preview_cache_key TEXT")
        if "preview_cache_truncated" not in columns:
            conn.execute("ALTER TABLE documents ADD COLUMN preview_cache_truncated INTEGER NOT NULL DEFAULT 0")
        if "preview_cached_at" not in columns:
            conn.execute("ALTER TABLE documents ADD COLUMN preview_cached_at TEXT")
        if "preview_cache_error" not in columns:
            conn.execute("ALTER TABLE documents ADD COLUMN preview_cache_error TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(content_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_review ON documents(review_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_uploader_key ON documents(uploader_key)")


def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(path: Path | None = None) -> Generator[sqlite3.Connection, None, None]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
