"""Request IDs, metrics, consistent error responses and API versioning."""
import time
import uuid
from collections import defaultdict

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from src.helpers.logging_config import get_logger, request_id_var

logger = get_logger("http")

CODES = {
    400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found", 409: "conflict",
    413: "payload_too_large", 415: "unsupported_media_type", 422: "validation_error", 429: "rate_limited",
    500: "internal_error", 502: "bad_gateway", 503: "service_unavailable",
}


class Metrics:
    def __init__(self):
        self.started = time.time()
        self.requests: dict[tuple[str, str, int], int] = defaultdict(int)
        self.latency_ms: dict[tuple[str, str], float] = defaultdict(float)

    def record(self, method: str, route: str, status: int, elapsed_ms: float):
        self.requests[(method, route, status)] += 1
        self.latency_ms[(method, route)] += elapsed_ms

    def snapshot(self) -> dict:
        total = sum(self.requests.values())
        errors = sum(n for (_, _, s), n in self.requests.items() if s >= 500)
        per_route = defaultdict(lambda: {"count": 0, "errors_5xx": 0, "avg_ms": 0.0})
        for (method, route, status), count in self.requests.items():
            item = per_route[f"{method} {route}"]
            item["count"] += count
            if status >= 500:
                item["errors_5xx"] += count
        for (method, route), total_ms in self.latency_ms.items():
            item = per_route[f"{method} {route}"]
            item["avg_ms"] = round(total_ms / item["count"], 1) if item["count"] else 0.0
        return {"uptime_seconds": int(time.time() - self.started), "requests_total": total,
                "server_errors_total": errors, "routes": dict(per_route)}

    def prometheus(self) -> str:
        lines = ["# TYPE http_requests_total counter"]
        for (method, route, status), count in sorted(self.requests.items()):
            lines.append(f'http_requests_total{{method="{method}",route="{route}",status="{status}"}} {count}')
        lines.append("# TYPE http_request_duration_ms_sum counter")
        for (method, route), total_ms in sorted(self.latency_ms.items()):
            lines.append(f'http_request_duration_ms_sum{{method="{method}",route="{route}"}} {total_ms:.1f}')
        lines.append(f"process_uptime_seconds {int(time.time() - self.started)}")
        return "\n".join(lines) + "\n"


metrics = Metrics()


class ApiVersionMiddleware:
    """Serve every /api/... endpoint at /api/v1/... as well (the v1 contract)."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] in ("http", "websocket") and scope["path"].startswith("/api/v1/"):
            scope = dict(scope)
            scope["path"] = "/api/" + scope["path"][len("/api/v1/"):]
            scope["raw_path"] = scope["path"].encode()
        await self.app(scope, receive, send)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Accept a caller's id only if it's short and plain, so it can't inject into logs.
        incoming = request.headers.get("x-request-id", "")
        safe = incoming.isascii() and 0 < len(incoming) <= 64 and incoming.replace("-", "").isalnum()
        request_id = incoming if safe else uuid.uuid4().hex
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"
            return response
        finally:
            request_id_var.reset(token)
            elapsed = (time.perf_counter() - start) * 1000
            route = request.scope.get("route")
            route_path = getattr(route, "path", "unmatched")
            metrics.record(request.method, route_path, status, elapsed)
            if status >= 500:
                logger.error(f"{request.method} {request.url.path} -> {status} in {elapsed:.0f}ms (request {request_id})")


def error_body(status: int, message, request: Request, details=None) -> dict:
    return {
        "detail": message,
        "error": {
            "code": CODES.get(status, "error"),
            "status": status,
            "message": message if isinstance(message, str) else "Request could not be processed.",
            "details": details,
            "request_id": getattr(request.state, "request_id", None),
        },
    }


def install_error_handlers(app: FastAPI):
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content=jsonable_encoder(error_body(exc.status_code, exc.detail, request)),
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e.get("loc", ())), "message": e.get("msg")} for e in exc.errors()]
        body = error_body(422, "Some fields are missing or invalid.", request, details)
        body["detail"] = jsonable_encoder(exc.errors())
        return JSONResponse(status_code=422, content=jsonable_encoder(body))

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception):
        logger.exception(f"Unhandled error on {request.method} {request.url.path}: {exc}")
        return JSONResponse(status_code=500, content=error_body(500, "Something went wrong. Please try again.", request))
