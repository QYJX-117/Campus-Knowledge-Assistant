from typing import Literal

from pydantic import BaseModel, Field


class DocumentRecord(BaseModel):
    id: int; title: str; filename: str; status: str; chunk_count: int
    size: int; mime_type: str = ""; error: str | None = None
    category: str | None = None; uploader_name: str | None = None
    created_at: str; updated_at: str


class DocumentBatchBody(BaseModel):
    action: Literal["delete", "reprocess"]
    ids: list[int] = Field(min_length=1, max_length=100)


class DocumentReviewBody(BaseModel):
    action: Literal["approve", "reject"]
    note: str = Field(default="", max_length=500)


class DocumentSearchBody(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    topK: int = Field(default=5, ge=1, le=20)
