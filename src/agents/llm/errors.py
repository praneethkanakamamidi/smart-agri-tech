"""Error taxonomy for model calls. `retriable` decides whether the router retries the same model."""
import json


class LLMError(Exception):
    code = "llm_error"
    retriable = False
    opens_circuit = False  # repeated failures of this kind disable the model for a while

    def __init__(self, message: str = "", *, status: int | None = None, retry_after: float | None = None):
        super().__init__(message or self.code)
        self.status = status
        self.retry_after = retry_after


class LLMTimeout(LLMError):
    code = "timeout"
    retriable = True
    opens_circuit = True


class LLMConnectionError(LLMError):
    code = "connection_error"
    retriable = True
    opens_circuit = True


class LLMRateLimited(LLMError):
    code = "rate_limited"
    retriable = True


class LLMServerError(LLMError):
    code = "server_error"
    retriable = True
    opens_circuit = True


class LLMAuthError(LLMError):
    """Bad or missing credentials: retrying won't help, and the model is taken out of rotation."""
    code = "auth_error"
    opens_circuit = True


class LLMBadRequest(LLMError):
    code = "bad_request"


class LLMContentFiltered(LLMError):
    code = "content_filtered"


class LLMOutputInvalid(LLMError):
    """The model answered, but not with output that validates against the requested schema."""
    code = "output_invalid"


class NoCapableModel(LLMError):
    """No configured, available model has every capability the task needs."""
    code = "no_capable_model"


class LLMUnavailable(LLMError):
    """Every capable model failed."""
    code = "all_models_failed"

    def __init__(self, message: str, attempts: list[dict]):
        super().__init__(message)
        self.attempts = attempts


class LLMQuotaExceeded(LLMError):
    code = "quota_exceeded"


def classify_http_error(status: int, body: str, headers) -> LLMError:
    retry_after = None
    raw_retry = headers.get("retry-after") if headers else None
    if raw_retry:
        try:
            retry_after = float(raw_retry)
        except ValueError:
            retry_after = None
    message = _error_message(body)
    if status in (401, 403):
        return LLMAuthError(message, status=status)
    if status == 429:
        return LLMRateLimited(message, status=status, retry_after=retry_after)
    if status in (408, 504):
        return LLMTimeout(message, status=status)
    if status >= 500:  # includes Anthropic's 529 "overloaded"
        return LLMServerError(message, status=status, retry_after=retry_after)
    if "content" in message.lower() and ("policy" in message.lower() or "filter" in message.lower()):
        return LLMContentFiltered(message, status=status)
    return LLMBadRequest(message, status=status)


def _error_message(body: str) -> str:
    """Short provider error text, never the whole body (it can echo the prompt)."""
    try:
        data = json.loads(body)
        error = data.get("error", data)
        if isinstance(error, dict):
            return str(error.get("message") or error.get("type") or "")[:300]
        return str(error)[:300]
    except (ValueError, AttributeError):
        return (body or "")[:200]
