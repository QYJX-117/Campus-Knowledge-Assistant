from typing import Literal

from pydantic import BaseModel, Field


class ChatBody(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    conversation_id: int | None = None
    strategy: Literal["hybrid", "dense", "bm25", "hyde", "multi", "decompose", "parent_child", "full"] = "hybrid"


class SourceRecord(BaseModel):
    index: int; title: str; content: str; score: float
    source_url: str = ""; category: str = ""


class FeedbackBody(BaseModel):
    conversation_id: int; message_id: int; helpful: bool
