from app.database import connect, utc_now
from app.rag.engine import rag_engine
from app.services.chat_service import ChatService


def test_new_chat_releases_sqlite_write_lock_before_stream(client, monkeypatch):
    events = iter([
        'event: meta\ndata: {"sources": []}\n\n',
        'event: token\ndata: {"text": "测试回答"}\n\n',
        'event: done\ndata: {}\n\n',
    ])
    monkeypatch.setattr(rag_engine, "stream_query", lambda *args, **kwargs: events)

    with connect() as db:
        admin_id = db.execute(
            "SELECT id FROM users WHERE email='admin@campus.example'"
        ).fetchone()["id"]
        stream = ChatService.stream_chat(db, "测试数据库锁", admin_id)
        next(stream)
        assert not db.in_transaction

        with connect() as audit_db:
            audit_db.execute("PRAGMA busy_timeout = 100")
            audit_db.execute(
                "INSERT INTO api_logs(user_id,endpoint,method,status_code,duration_ms,created_at) VALUES(?,?,?,?,?,?)",
                (admin_id, "/api/test", "GET", 200, 1, utc_now()),
            )
            audit_db.commit()

        list(stream)
