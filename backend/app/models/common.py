from datetime import datetime, timezone
from typing import Any, Generic, TypeVar
from pydantic import BaseModel

T = TypeVar("T")


class Result(BaseModel, Generic[T]):
    code: int = 200
    message: str = "success"
    data: T | None = None
    timestamp: str = datetime.now(timezone.utc).isoformat()

    @classmethod
    def ok(cls, data: T) -> "Result[T]":
        return cls(code=200, message="success", data=data)

    @classmethod
    def error(cls, code: int, message: str) -> "Result[None]":
        return cls(code=code, message=message, data=None)
