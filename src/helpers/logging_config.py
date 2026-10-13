"""
Structured JSON logging.

- LOG_LEVEL (default INFO) sets the level.
- Logs go to stdout (the container/12-factor norm). Set LOG_FILE=logs/app.log to also write a file.
- Every record carries the current request id (set by RequestContextMiddleware) when there is one.
"""
import json
import logging
import os
from contextvars import ContextVar
from datetime import datetime, timezone

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_STANDARD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}


class JSONFormatter(logging.Formatter):
    """Formats log records as one JSON object per line."""

    def format(self, record):
        log_obj = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        request_id = request_id_var.get()
        if request_id:
            log_obj["request_id"] = request_id
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        # Fields passed with `extra={...}` (and the older `extra_fields` convention).
        for key, value in record.__dict__.get("extra_fields", {}).items():
            log_obj.setdefault(key, value)
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and key != "extra_fields" and not key.startswith("_"):
                log_obj.setdefault(key, value)
        return json.dumps(log_obj, default=str)


def _configure_root():
    root = logging.getLogger()
    if getattr(root, "_smart_agri_configured", False):
        return
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    for handler in list(root.handlers):
        root.removeHandler(handler)
    stream = logging.StreamHandler()
    stream.setFormatter(JSONFormatter())
    root.addHandler(stream)
    log_file = os.getenv("LOG_FILE")
    if log_file:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(JSONFormatter())
        root.addHandler(file_handler)
    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).setLevel(os.getenv("ACCESS_LOG_LEVEL", "WARNING").upper())
    root._smart_agri_configured = True


def get_logger(name):
    """Return a logger that emits structured JSON (configures the root logger once)."""
    _configure_root()
    return logging.getLogger(name)
