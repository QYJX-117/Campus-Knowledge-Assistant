"""Chat service — RAG orchestration + conversation management + trace logging."""

import json
import sqlite3
import time

from ..database import connect, utc_now
from ..rag.engine import rag_engine
from ..utils.trace_logger import generate_trace_id, save_trace
from ..rag.hot_cache import add_to_hot_faq as hot_cache_add


class ChatService:

    @staticmethod
    def owns_conversation(db: sqlite3.Connection, conversation_id: int, user_id: int) -> bool:
        return db.execute(
            "SELECT 1 FROM conversations WHERE id=? AND user_id=?",
            (conversation_id, user_id),
        ).fetchone() is not None

    @staticmethod
    def stream_chat(db: sqlite3.Connection, question: str, user_id: int, conversation_id: int | None = None, strategy: str = "hybrid"):
        now = utc_now()
        t_start = time.time()
        trace_id = generate_trace_id()

        if not conversation_id:
            cur = db.execute("INSERT INTO conversations(user_id,title,created_at,updated_at) VALUES(?,?,?,?)",
                             (user_id, question[:28], now, now))
            conversation_id = int(cur.lastrowid)
            # Release SQLite's write lock before retrieval and the external LLM
            # stream. Otherwise the audit middleware cannot write its log and
            # every API response waits behind this long-running transaction.
            db.commit()

        full_answer = ""
        sources = []
        hot_hit = False
        for event in rag_engine.stream_query(question, conversation_id, strategy):
            if "event: meta" in event:
                try:
                    data = json.loads(event.split("data: ", 1)[1])
                    sources = data.get("sources", [])
                    hot_hit = data.get("hot_hit", False)
                    data["conversation_id"] = conversation_id
                    event = f"event: meta\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                except Exception:
                    pass
            elif "event: token" in event:
                try:
                    data = json.loads(event.split("data: ", 1)[1])
                    full_answer += data.get("text", "")
                except Exception:
                    pass
            yield event

        db.execute("INSERT INTO messages(conversation_id,role,content,sources,created_at) VALUES(?,'USER',?,'[]',?)",
                   (conversation_id, question, now))
        db.execute("INSERT INTO messages(conversation_id,role,content,sources,created_at) VALUES(?,'ASSISTANT',?,?,?)",
                   (conversation_id, full_answer, json.dumps(sources, ensure_ascii=False), utc_now()))
        db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (utc_now(), conversation_id))
        db.commit()

        # Trace logging (Design fusion)
        cost_time = round(time.time() - t_start, 3)
        save_trace({
            "trace_id": trace_id, "session_id": str(conversation_id),
            "question": question, "answer": full_answer,
            "sources": sources, "hot_hit": hot_hit,
            "strategy": strategy, "user_id": user_id,
            "cost_time": cost_time,
        })

    @staticmethod
    def list_conversations(db: sqlite3.Connection, user_id: int) -> list[dict]:
        rows = db.execute("""
            SELECT c.*, COUNT(m.id) AS message_count
            FROM conversations c LEFT JOIN messages m ON m.conversation_id=c.id
            WHERE c.user_id=? GROUP BY c.id ORDER BY c.updated_at DESC
        """, (user_id,)).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_conversation(db: sqlite3.Connection, conversation_id: int, user_id: int) -> dict | None:
        conv = db.execute("SELECT * FROM conversations WHERE id=? AND user_id=?", (conversation_id, user_id)).fetchone()
        if not conv:
            return None
        msgs = db.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY id", (conversation_id,)).fetchall()
        return dict(conv) | {"messages": [dict(m) | {"sources": json.loads(m["sources"])} for m in msgs]}

    @staticmethod
    def delete_conversation(db: sqlite3.Connection, conversation_id: int, user_id: int) -> bool:
        cur = db.execute("DELETE FROM conversations WHERE id=? AND user_id=?", (conversation_id, user_id))
        db.commit()
        return cur.rowcount > 0
