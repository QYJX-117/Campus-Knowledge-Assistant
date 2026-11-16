"""FastAPI application entry point."""

import threading
import time
from collections.abc import Iterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import init_database, connect, utc_now
from .security import decode_token, hash_password
from .rag.engine import rag_engine

# Import all API routers
from .api.auth import router as auth_router
from .api.chat import router as chat_router
from .api.documents import course_router as document_course_router, router as documents_router
from .services.document_service import DocumentService
from .api.users import router as users_router
from .api.stats import router as stats_router


def seed_database() -> None:
    """Idempotent: create admin user + seed sample document on first start."""
    with connect() as db:
        # Admin user
        admin = db.execute("SELECT id FROM users WHERE email=?", ("admin@campus.example",)).fetchone()
        if not admin:
            cur = db.execute(
                "INSERT INTO users(name,email,password_hash,role,is_active,created_at) VALUES(?,?,?,?,?,?)",
                ("系统管理员", "admin@campus.example", hash_password("admin123"), "ADMIN", 1, utc_now()),
            )
            admin_id = int(cur.lastrowid)
        else:
            admin_id = int(admin["id"])

        # Guest users don't have accounts — handled by guest token in security.py

        # Seed document (HHU guide)
        sample = (
            "河海大学是一所拥有111年办学历史，以水利为特色、工科为主，"
            '多学科协调发展的教育部直属全国重点大学，是国家"双一流"建设、'
            '"211工程"重点建设、"985工程优势学科创新平台"建设以及'
            "经国家批准设立研究生院的高校。\n\n"
            "河海大学的校训是：艰苦朴素、实事求是、严格要求、勇于探索。\n\n"
            "图书馆周一至周五开放时间为 08:00 至 22:00，周末开放时间为 "
            "09:00 至 21:00。法定节假日安排以图书馆公告为准。\n\n"
            "校园卡补办：学生遗失校园卡后，可先在校园服务 App 中挂失，再携带学生证前往"
            "行政楼一层校园卡服务中心补办。补办工本费为 20 元。\n\n"
            "奖学金申请：综合奖学金每学年评定一次，申请人需完成本学年培养方案规定课程，"
            "无违纪记录，并在学院通知期限内提交申请表和成绩证明。"
        )
        seed_path = settings.upload_dir / "seed-hhu-guide.md"
        seed_path.write_bytes(sample.encode("utf-8"))

        existing = db.execute("SELECT id,status,chunk_count FROM documents WHERE stored_name='seed-hhu-guide.md'").fetchone()
        if existing and existing["status"] == "READY" and existing["chunk_count"] > 0:
            return

        if not existing:
            now = utc_now()
            cur = db.execute(
                "INSERT INTO documents(title,filename,stored_name,mime_type,size,status,chunk_count,uploaded_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("河海大学校园服务指南（示例）", "hhu-guide.md", "seed-hhu-guide.md", "text/markdown", len(sample.encode()), "PROCESSING", 0, admin_id, now, now),
            )
            doc_id = int(cur.lastrowid)
        else:
            doc_id = int(existing["id"])

        try:
            rag_engine.add_document(seed_path, document_id=doc_id, title="河海大学校园服务指南（示例）", category="校园服务", db=db)
        except Exception as e:
            print(f"[WARN] Seed document indexing failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> Iterator[None]:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    init_database()
    # In-process background jobs cannot survive a server restart.  Make the
    # interruption visible and retryable instead of leaving endless spinners.
    with connect() as db:
        DocumentService.mark_interrupted_as_failed(db)
    try:
        _ = rag_engine  # Force RAG engine init
        print("[OK] RAG engine initialized")
    except Exception as e:
        print(f"[WARN] RAG engine init failed: {e}")
    seed_database()

    # Load knowledge base synchronously during startup so the lock is not
    # contended by background load vs. user requests.
    try:
        n = rag_engine.load_knowledge_base(settings.knowledge_base_dir)
        print(f"[OK] Knowledge base loaded: {n} docs")
    except Exception as e:
        print(f"[WARN] KB load failed: {e}")
    yield


from .middleware.security import RateLimitMiddleware

app = FastAPI(title="校园问答助手 API", version="2.0.0", lifespan=lifespan)
app.add_middleware(RateLimitMiddleware, max_requests=settings.rate_limit_per_minute, window=60)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def audit_requests(request: Request, call_next):
    """Persist lightweight operational logs without storing request bodies or secrets."""
    started = time.perf_counter()
    response = await call_next(request)
    if request.url.path != "/api/health":
        user_id = None
        authorization = request.headers.get("authorization", "")
        if authorization.startswith("Bearer "):
            payload = decode_token(authorization.removeprefix("Bearer ").strip())
            if payload and not payload.get("guest"):
                try:
                    user_id = int(payload["sub"])
                except (KeyError, TypeError, ValueError):
                    user_id = None
        try:
            with connect() as db:
                # Audit logging is best-effort. It must never hold a business
                # response for SQLite's normal single-writer contention.
                db.execute("PRAGMA busy_timeout = 100")
                db.execute(
                    "INSERT INTO api_logs(user_id,endpoint,method,status_code,duration_ms,created_at) VALUES(?,?,?,?,?,?)",
                    (user_id, request.url.path, request.method, response.status_code,
                     round((time.perf_counter() - started) * 1000), utc_now()),
                )
                db.commit()
        except Exception as exc:
            print(f"[WARN] Audit log write failed: {exc}")
    return response

# Register routers
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(documents_router)
app.include_router(document_course_router)
app.include_router(users_router)
app.include_router(stats_router)
