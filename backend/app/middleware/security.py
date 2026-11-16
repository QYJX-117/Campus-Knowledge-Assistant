"""Security middleware — rate limiting + input sanitization + security headers."""

import time
import hashlib
import hmac
from collections import defaultdict
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from ..config import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding window rate limiter per IP + endpoint."""

    def __init__(self, app, max_requests: int = 100, window: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window = window
        self._buckets: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next: Callable):
        if not settings.rate_limit_enabled:
            return await call_next(request)

        # Skip health check and static
        if request.url.path in ("/api/health", "/favicon.ico"):
            return await call_next(request)

        client = request.client.host if request.client else "unknown"
        key = f"{client}:{request.url.path}"
        now = time.time()
        cutoff = now - self.window

        # Clean expired entries
        self._buckets[key] = [t for t in self._buckets[key] if t > cutoff]

        if len(self._buckets[key]) >= self.max_requests:
            return JSONResponse(
                status_code=429,
                content={"code": 429, "message": "请求过于频繁，请稍后再试", "data": None},
            )

        self._buckets[key].append(now)

        response = await call_next(request)

        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["X-RateLimit-Remaining"] = str(self.max_requests - len(self._buckets[key]))

        return response


def sanitize_input(text: str, max_length: int = 10000) -> str:
    """Sanitize user input — strip control chars, limit length."""
    import re
    text = text[:max_length]
    # Remove control characters except newline, tab
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text.strip()
