"""
One-time passwords for phone/email verification, password reset and recovery.

Codes are numeric, generated with `secrets`, and stored only as keyed hashes.
Store: OTP_STORE=mongo (default, existing `otps` collection) or OTP_STORE=postgres.
"""
import os
import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import channels
from src.core.crypto import hash_secret, verify_secret
from src.data_models.platform_model import OtpCodes
from src.core.clock import utcnow

OTP_TTL_MINUTES = 10
OTP_ATTEMPTS = 3
OTP_LENGTH = 6

PURPOSES = ("verify_email", "verify_phone", "password_reset")


def generate_code(length: int = OTP_LENGTH) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(length))


def _store_kind() -> str:
    return os.getenv("OTP_STORE", "mongo").lower()


def _mongo_collection():
    from src.db_connections.mongo_conn import get_mongo_client

    return get_mongo_client()[os.getenv("MONGO_DB")]["otps"]


async def _save(db: AsyncSession, identifier: str, purpose: str, code_hash: str, expires_at: datetime):
    if _store_kind() == "postgres":
        await db.execute(delete(OtpCodes).where(OtpCodes.identifier == identifier, OtpCodes.purpose == purpose))
        db.add(OtpCodes(
            identifier=identifier, purpose=purpose, code_hash=code_hash, attempts_left=OTP_ATTEMPTS,
            expires_at=expires_at, created_at=utcnow(),
        ))
        await db.flush()
    else:
        await _mongo_collection().replace_one(
            {"user_name": identifier, "purpose": purpose},
            {"user_name": identifier, "purpose": purpose, "otp_hash": code_hash,
             "expires_at": expires_at, "attempts": OTP_ATTEMPTS},
            upsert=True,
        )


async def _load(db: AsyncSession, identifier: str, purpose: str) -> dict | None:
    if _store_kind() == "postgres":
        row = (await db.execute(select(OtpCodes).where(
            OtpCodes.identifier == identifier, OtpCodes.purpose == purpose
        ))).scalar_one_or_none()
        if not row:
            return None
        return {"otp_hash": row.code_hash, "expires_at": row.expires_at, "attempts": row.attempts_left}
    return await _mongo_collection().find_one({"user_name": identifier, "purpose": purpose})


async def _decrement(db: AsyncSession, identifier: str, purpose: str):
    if _store_kind() == "postgres":
        row = (await db.execute(select(OtpCodes).where(
            OtpCodes.identifier == identifier, OtpCodes.purpose == purpose
        ))).scalar_one()
        row.attempts_left -= 1
        await db.flush()
    else:
        await _mongo_collection().update_one({"user_name": identifier, "purpose": purpose}, {"$inc": {"attempts": -1}})


async def _remove(db: AsyncSession, identifier: str, purpose: str):
    if _store_kind() == "postgres":
        await db.execute(delete(OtpCodes).where(OtpCodes.identifier == identifier, OtpCodes.purpose == purpose))
        await db.flush()
    else:
        await _mongo_collection().delete_one({"user_name": identifier, "purpose": purpose})


async def issue(db: AsyncSession, identifier: str, purpose: str, channel: str, address: str, language_note: str = ""):
    """Create a code and send it over `channel` (sms | email). The caller commits for the postgres store."""
    code = generate_code()
    await _save(db, identifier, purpose, hash_secret(code), utcnow() + timedelta(minutes=OTP_TTL_MINUTES))
    title = "Smart Agri Tech verification code"
    body = f"Your verification code is {code}. It expires in {OTP_TTL_MINUTES} minutes. Do not share it. {language_note}".strip()
    try:
        await channels.send(channel, address, title, body)
    except channels.DeliveryError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Could not send the code: {e}")
    if os.getenv("OTP_DEBUG_ECHO", "false").lower() == "true":
        return code  # development/testing only
    return None


async def verify(db: AsyncSession, identifier: str, purpose: str, code: str):
    """Raise HTTPException unless `code` is valid. Consumes the code on success."""
    record = await _load(db, identifier, purpose)
    if not record or ("otp_hash" not in record):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active code. Request a new one.")
    if utcnow() > record["expires_at"]:
        await _remove(db, identifier, purpose)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Code expired. Request a new one.")
    if not verify_secret(code or "", record["otp_hash"]):
        if record["attempts"] > 1:
            await _decrement(db, identifier, purpose)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid code. {record['attempts'] - 1} attempts left.",
            )
        await _remove(db, identifier, purpose)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Maximum attempts reached. Request a new code.")
    await _remove(db, identifier, purpose)
