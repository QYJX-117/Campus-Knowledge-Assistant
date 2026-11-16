from pydantic import BaseModel


class DashboardStats(BaseModel):
    total_documents: int = 0; ready_documents: int = 0; total_chunks: int = 0
    pending_documents: int = 0; processing_documents: int = 0; error_documents: int = 0
    total_conversations: int = 0; total_users: int = 0; active_users: int = 0
    today_questions: int = 0; avg_latency_ms: float = 0.0


class TrendPoint(BaseModel):
    date: str; questions: int = 0; new_users: int = 0
