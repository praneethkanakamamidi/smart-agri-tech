"""Append-only audit trail. Calls queue a row on the caller's session; the caller commits."""
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.data_models.platform_model import AuditLogs
from src.core.clock import utcnow


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def audit(
    db: AsyncSession,
    action: str,
    entity_type: str,
    entity_id: Any = None,
    actor_id: int | None = None,
    actor_role: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    ip_address: str | None = None,
):
    db.add(AuditLogs(
        actor_id=actor_id,
        actor_role=actor_role,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        before=_jsonable(before) if before is not None else None,
        after=_jsonable(after) if after is not None else None,
        ip_address=ip_address,
        created_at=utcnow(),
    ))
