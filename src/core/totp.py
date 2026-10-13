"""RFC 6238 TOTP (Google Authenticator compatible) for admin multi-factor authentication."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP_SECONDS = 30
DIGITS = 6


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code_at(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** DIGITS)).zfill(DIGITS)


def current_code(secret: str, at: float | None = None) -> str:
    return _code_at(secret, int((at or time.time()) // STEP_SECONDS))


def verify(secret: str, code: str, window: int = 1) -> bool:
    """Accept the current code and +/- `window` steps for clock drift."""
    if not code or not code.isdigit():
        return False
    counter = int(time.time() // STEP_SECONDS)
    return any(
        hmac.compare_digest(_code_at(secret, counter + drift), code)
        for drift in range(-window, window + 1)
    )


def provisioning_uri(secret: str, account: str, issuer: str = "Smart-Agri-Tech") -> str:
    return (
        f"otpauth://totp/{quote(issuer)}:{quote(account)}"
        f"?secret={secret}&issuer={quote(issuer)}&digits={DIGITS}&period={STEP_SECONDS}"
    )
