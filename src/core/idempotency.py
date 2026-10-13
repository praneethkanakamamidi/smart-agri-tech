"""
Idempotency-Key support for critical writes (order creation, offer acceptance, payments).

A retried request with the same key and body returns the stored response instead of
repeating the side effect. A reused key with a different body is rejected.
"""
import hashlib
import json
from datetime import datetime
from typing import Awaitable, Callable

from fastapi import HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.data_models.platform_model import IdempotencyKeys


def _hash(payload) -> str:
    return hashlib.sha256(
        json.dumps(jsonable_encoder(payload), sort_keys=True, default=str).encode()
    ).hexdigest()


async def run_idempotent(
    db: AsyncSession,
    key: str | None,
    user_id: int,
    endpoint: str,
    payload,
    action: Callable[[], Awaitable[dict]],
) -> dict:
    if not key:
        return await action()
    if len(key) > 100:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Idempotency-Key is too long.")

    request_hash = _hash(payload)
    existing = (await db.execute(
        select(IdempotencyKeys).where(
            IdempotencyKeys.user_id == user_id,
            IdempotencyKeys.endpoint == endpoint,
            IdempotencyKeys.key == key,
        )
    )).scalar_one_or_none()
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This Idempotency-Key was already used with a different request.",
            )
        if existing.response is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The original request is still in progress.")
        return existing.response

    result = await action()
    try:
        db.add(IdempotencyKeys(
            user_id=user_id, endpoint=endpoint, key=key, request_hash=request_hash,
            status_code=200, response=jsonable_encoder(result), created_at=datetime.utcnow(),
        ))
        await db.commit()
    except IntegrityError:
        # A concurrent request with the same key finished first; its side effect is the one that counts.
        await db.rollback()
    return result
