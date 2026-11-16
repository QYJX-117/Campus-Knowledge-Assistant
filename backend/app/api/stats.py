"""Statistics + health routes."""

import sqlite3
from fastapi import APIRouter, Depends, Query
from ..services.stats_service import StatsService
from ..models.common import Result
from ..database import get_db
from .chat import admin_user, current_user

router = APIRouter(prefix="/api", tags=["stats"])


@router.get("/health")
def health():
    return {"status": "ok", "version": "2.0.0"}


@router.get("/stats/dashboard")
def dashboard(db: sqlite3.Connection = Depends(get_db), _=Depends(admin_user)):
    return Result.ok(StatsService.dashboard(db))


@router.get("/stats/trends")
def trends(days: int = Query(7, ge=1, le=90), db: sqlite3.Connection = Depends(get_db), _=Depends(admin_user)):
    return Result.ok(StatsService.trends(db, days))


@router.get("/system/logs")
def system_logs(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(admin_user),
):
    total = int(db.execute("SELECT COUNT(*) FROM api_logs").fetchone()[0])
    rows = db.execute(
        """
        SELECT l.id,l.endpoint,l.method,l.status_code,l.duration_ms,l.created_at,
               COALESCE(u.name, CASE WHEN l.user_id IS NULL THEN '访客/未登录' ELSE '已删除用户' END) AS actor
        FROM api_logs l LEFT JOIN users u ON u.id=l.user_id
        ORDER BY l.id DESC LIMIT ? OFFSET ?
        """,
        (size, (page - 1) * size),
    ).fetchall()
    return Result.ok({
        "records": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "size": size,
    })


@router.get("/stats")
def stats(db: sqlite3.Connection = Depends(get_db), _=Depends(current_user)):
    return Result.ok({
        "documents": db.execute("SELECT COUNT(*) FROM documents WHERE status='READY'").fetchone()[0],
        "chunks": len(__import__("..rag.engine", fromlist=["rag_engine"]).rag_engine.index.docstore.docs),
        "conversations": db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0],
    })


@router.get("/quick-questions")
def quick_questions(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute("SELECT * FROM quick_questions WHERE is_active=1 ORDER BY sort_order").fetchall()
    return Result.ok([dict(r) for r in rows])


@router.post("/quick-questions")
def add_quick_question(body: dict, db: sqlite3.Connection = Depends(get_db), _=Depends(admin_user)):
    db.execute("INSERT INTO quick_questions(question,category,sort_order) VALUES(?,?,?)",
               (body["question"], body.get("category", ""), body.get("sort_order", 0)))
    db.commit()
    return Result.ok(None)


@router.delete("/quick-questions/{qid}", status_code=204)
def delete_quick_question(qid: int, db: sqlite3.Connection = Depends(get_db), _=Depends(admin_user)):
    db.execute("DELETE FROM quick_questions WHERE id=?", (qid,))
    db.commit()


# ── System Config ────────────────────────────────────────
@router.get("/system/config")
def list_config(db: sqlite3.Connection = Depends(get_db), _=Depends(admin_user)):
    rows = db.execute("SELECT key, value, description FROM system_config").fetchall()
    return Result.ok([dict(r) for r in rows])


@router.put("/system/config")
def update_config(body: dict, db: sqlite3.Connection = Depends(get_db), _=Depends(admin_user)):
    from ..database import utc_now
    db.execute(
        "INSERT OR REPLACE INTO system_config(key, value, description, updated_at) VALUES(?,?,?,?)",
        (body["key"], str(body["value"]), body.get("description", ""), utc_now()),
    )
    db.commit()
    return Result.ok(None)


# ── KB Versions ──────────────────────────────────────────
@router.get("/kb/versions")
def list_kb_versions(db: sqlite3.Connection = Depends(get_db), _=Depends(admin_user)):
    rows = db.execute("SELECT * FROM kb_versions ORDER BY created_at DESC LIMIT 20").fetchall()
    return Result.ok([dict(r) for r in rows])


@router.post("/kb/rebuild")
def rebuild_kb(db: sqlite3.Connection = Depends(get_db), _=Depends(admin_user)):
    import time as _time
    from ..database import utc_now
    from ..rag.engine import rag_engine

    start = _time.time()
    rag_engine.rebuild_index()
    elapsed = int((_time.time() - start) * 1000)
    doc_count = db.execute("SELECT COUNT(*) FROM documents WHERE status='READY'").fetchone()[0]
    chunk_count = len(rag_engine.index.docstore.docs)
    db.execute(
        "INSERT INTO kb_versions(version_tag, document_count, chunk_count, build_duration_ms, status, created_at) VALUES(?,?,?,?,?,?)",
        (f"v{utc_now()[:16]}", doc_count, chunk_count, elapsed, "ready", utc_now()),
    )
    db.commit()
    return Result.ok({"document_count": doc_count, "chunk_count": chunk_count, "duration_ms": elapsed})
