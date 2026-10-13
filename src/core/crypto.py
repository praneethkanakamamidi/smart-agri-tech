"""Field-level encryption for sensitive data at rest (bank account, UPI id, MFA secrets)."""
import base64
import hashlib
import hmac
import os

from cryptography.fernet import Fernet, InvalidToken

from src.helpers.logging_config import get_logger

logger = get_logger(__name__)


def _build_fernet() -> Fernet:
    key = os.getenv("DATA_ENCRYPTION_KEY")
    if key:
        return Fernet(key.encode())
    # Fallback keeps development working; production must set DATA_ENCRYPTION_KEY
    # (generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())").
    seed = os.getenv("ACCESS_TOKEN", "smart-agri-tech-dev-only")
    logger.warning("DATA_ENCRYPTION_KEY is not set; deriving an encryption key from ACCESS_TOKEN.")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(f"enc:{seed}".encode()).digest()))


_fernet = _build_fernet()


def encrypt(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return _fernet.encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet.decrypt(value.encode()).decode()
    except InvalidToken:
        logger.error("Failed to decrypt a stored value (wrong DATA_ENCRYPTION_KEY?).")
        return None


def mask(value: str | None, visible: int = 4) -> str | None:
    if not value:
        return None
    return "•" * max(len(value) - visible, 0) + value[-visible:]


def hash_secret(value: str) -> str:
    """Keyed hash for OTPs / delivery codes (never store them in clear text)."""
    pepper = os.getenv("ACCESS_TOKEN", "smart-agri-tech-dev-only").encode()
    return hmac.new(pepper, value.encode(), hashlib.sha256).hexdigest()


def verify_secret(value: str, hashed: str | None) -> bool:
    return bool(hashed) and hmac.compare_digest(hash_secret(value), hashed)
