"""
In-process sliding-window rate limiter.

Limits are per process: with several workers or hosts, put a shared limiter
(e.g. Redis or the API gateway) in front for exact global limits.
"""
import os
import time
from collections import defaultdict, deque

from fastapi import HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class SlidingWindowLimiter:
    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and hits[0] <= now - window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True

    def check(self, key: str, limit: int, window_seconds: int = 60):
        """Raise 429 when `key` exceeded `limit` calls in the window."""
        if rate_limiting_enabled() and not self.allow(key, limit, window_seconds):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please slow down and try again shortly.",
            )

    def reset(self):
        self._hits.clear()


limiter = SlidingWindowLimiter()


def rate_limiting_enabled() -> bool:
    return os.getenv("RATE_LIMIT_ENABLED", "true").lower() != "false"


# (path prefix, requests, window seconds) - most specific first.
SENSITIVE_RULES = (
    ("/api/login", 10, 60),
    ("/api/auth/", 10, 60),
    ("/api/verify-otp", 10, 60),
    ("/api/users", 20, 60),
    ("/api/token/refresh", 30, 60),
)
DEFAULT_RULE = (300, 60)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and os.getenv("TRUST_PROXY_HEADERS", "false").lower() == "true":
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if rate_limiting_enabled():
            ip = client_ip(request)
            path = request.url.path
            limit, window = DEFAULT_RULE
            bucket = "default"
            if request.method in ("POST", "PUT"):
                for prefix, rule_limit, rule_window in SENSITIVE_RULES:
                    if path.startswith(prefix):
                        limit, window, bucket = rule_limit, rule_window, prefix
                        break
            if not limiter.allow(f"{bucket}:{ip}", limit, window):
                from src.core.observability import error_body

                return JSONResponse(
                    status_code=429,
                    content=error_body(429, "Too many requests. Please slow down and try again shortly.", request),
                    headers={"Retry-After": str(window)},
                )
        return await call_next(request)
