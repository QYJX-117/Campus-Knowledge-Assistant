"""Statistics service for dashboard."""

import sqlite3

from ..database import utc_now
from ..rag.engine import rag_engine
from ..models.stats import DashboardStats, TrendPoint


class StatsService:

    @staticmethod
    def dashboard(db: sqlite3.Connection) -> DashboardStats:
        now = utc_now()
        today = now[:10]
        total_docs = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        ready_docs = db.execute("SELECT COUNT(*) FROM documents WHERE status='READY'").fetchone()[0]
        pending_docs = db.execute("SELECT COUNT(*) FROM documents WHERE review_status='PENDING'").fetchone()[0]
        processing_docs = db.execute("SELECT COUNT(*) FROM documents WHERE status='PROCESSING'").fetchone()[0]
        error_docs = db.execute("SELECT COUNT(*) FROM documents WHERE status='ERROR'").fetchone()[0]
        total_chunks = len(rag_engine.index.docstore.docs)
        total_conv = db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        total_users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active_users = db.execute("SELECT COUNT(*) FROM users WHERE is_active=1").fetchone()[0]
        today_q = db.execute("SELECT COUNT(*) FROM messages WHERE role='USER' AND created_at>=?", (today,)).fetchone()[0]
        latencies = db.execute("SELECT duration_ms FROM api_logs WHERE endpoint='/api/chat/stream' AND created_at>=?", (today,)).fetchall()
        avg_lat = sum(r[0] for r in latencies) / len(latencies) if latencies else 0.0
        return DashboardStats(
            total_documents=total_docs, ready_documents=ready_docs, total_chunks=total_chunks,
            pending_documents=pending_docs, processing_documents=processing_docs, error_documents=error_docs,
            total_conversations=total_conv, total_users=total_users, active_users=active_users,
            today_questions=today_q, avg_latency_ms=round(avg_lat, 1),
        )

    @staticmethod
    def trends(db: sqlite3.Connection, days: int = 7) -> list[TrendPoint]:
        from datetime import datetime, timedelta, timezone
        points = []
        for i in range(days - 1, -1, -1):
            d = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
            q = db.execute("SELECT COUNT(*) FROM messages WHERE role='USER' AND created_at>=? AND created_at<?", (d, f"{d}T23:59:59")).fetchone()[0]
            u = db.execute("SELECT COUNT(*) FROM users WHERE created_at>=? AND created_at<?", (d, f"{d}T23:59:59")).fetchone()[0]
            points.append(TrendPoint(date=d, questions=q, new_users=u))
        return points
