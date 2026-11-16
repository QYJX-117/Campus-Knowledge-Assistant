"""CLI: Build knowledge base index from Markdown files."""

from .config import settings
from .database import init_database, connect, utc_now
from .rag.engine import rag_engine
from .security import hash_password


def _ensure_system_user() -> int:
    with connect() as db:
        row = db.execute("SELECT id FROM users WHERE email=?", ("system@campus.example",)).fetchone()
        if row:
            return int(row["id"])
        cur = db.execute(
            "INSERT INTO users(name,email,password_hash,role,is_active,created_at) VALUES(?,?,?,?,?,?)",
            ("系统", "system@campus.example", hash_password("system"), "ADMIN", 1, utc_now()),
        )
        db.commit()
        return int(cur.lastrowid)


def main() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    init_database()
    uid = _ensure_system_user()
    print(f"Building index from: {settings.knowledge_base_dir}")
    count = rag_engine.load_knowledge_base(settings.knowledge_base_dir, uploaded_by=uid)
    print(f"Done. {count} documents indexed.")


if __name__ == "__main__":
    main()
