"""Masks personal data before anything is logged or written to the agent trace."""
import re
from typing import Any

_PATTERNS = (
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),  # before UPI: emails have a dotted domain
    (re.compile(r"[\w.\-]{2,}@[A-Za-z]{2,}(?![\w.])"), "[upi]"),
    (re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)"), "[phone]"),
    (re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b"), "[ifsc]"),
    (re.compile(r"(?<!\d)\d{4}\s?\d{4}\s?\d{4}(?!\d)"), "[id-number]"),  # Aadhaar-like 12 digits
    (re.compile(r"(?<!\d)\d{9,18}(?!\d)"), "[account-number]"),
)
SENSITIVE_KEYS = {
    "password", "token", "access_token", "refresh_token", "api_key", "authorization", "otp", "delivery_code",
    "bank_account_number", "upi_id", "mfa_secret", "secret",
}
MAX_STRING = 600


def redact_text(value: str) -> str:
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    return value if len(value) <= MAX_STRING else value[:MAX_STRING] + "…"


def redact(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return "[truncated]"
    if isinstance(value, dict):
        return {k: ("[redacted]" if str(k).lower() in SENSITIVE_KEYS else redact(v, depth + 1)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, depth + 1) for v in list(value)[:50]]
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, bytes):
        return f"[{len(value)} bytes]"
    return value
