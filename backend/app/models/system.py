from pydantic import BaseModel, Field
from typing import Any


class SystemConfigItem(BaseModel):
    key: str; value: Any; description: str = ""


class QuickQuestion(BaseModel):
    id: int | None = None
    question: str = Field(min_length=2, max_length=200)
    category: str = ""; sort_order: int = 0; is_active: bool = True
