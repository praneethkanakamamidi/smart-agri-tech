"""Admin-configurable marketplace settings with versioned history."""
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data_models.platform_model import PlatformSettings, PlatformSettingsHistory
from src.core.clock import utcnow

DEFAULT_SETTINGS: dict[str, dict[str, Any]] = {
    "offer_expiry_hours": {"value": 48, "description": "Default validity of an offer, in hours."},
    "offer_max_expiry_hours": {"value": 168, "description": "Longest validity a user may set on an offer."},
    "offer_expiry_warning_hours": {"value": 2, "description": "Notify parties this many hours before an offer expires."},
    "order_confirmation_hours": {"value": 24, "description": "Time to confirm a new order before its stock reservation is released."},
    "auto_complete_days": {"value": 3, "description": "Delivered orders with no dispute auto-complete after this many days (if fully paid)."},
    "dispute_window_days": {"value": 7, "description": "Days after delivery during which a dispute can be raised."},
    "platform_fee_percent": {"value": 0, "description": "Platform commission as % of the produce subtotal."},
    "platform_fee_payer": {"value": "vendor", "description": "Who pays the platform fee: vendor (added to payable) or farmer (deducted from settlement)."},
    "tax_percent_on_fee": {"value": 18, "description": "Tax (e.g. GST) charged on the platform fee, in %."},
    "partial_advance_percent": {"value": 30, "description": "Default advance % for partial_advance payment terms."},
    "pay_on_delivery_requires_verification": {"value": True, "description": "Only VERIFIED vendors may use pay-on-delivery terms."},
    "high_value_order_threshold": {"value": 100000, "description": "Orders at or above this amount require both parties to be VERIFIED."},
    "listing_expiry_warning_days": {"value": 1, "description": "Notify the farmer this many days before a listing expires."},
    "max_upload_mb": {"value": 5, "description": "Maximum upload size in MB."},
    "min_sample_size": {"value": 5, "description": "Minimum data points before a statistic is shown as reliable."},
    "price_change_alert_percent": {"value": 10, "description": "Week-over-week deal price change that triggers an alert."},
    "message_rate_per_minute": {"value": 30, "description": "Max chat messages a user can send per minute."},
    "cancellation_policy": {
        "value": {
            "pending_confirmation": "either_party",
            "confirmed": "either_party",
            "preparing": "farmer_or_request",
            "ready_for_pickup": "farmer_or_request",
            "in_transit": "dispute_only",
            "delivered": "dispute_only",
        },
        "description": "Who may cancel at each order stage.",
    },
    "account_deletion_grace_days": {"value": 30, "description": "Days before a deletion request anonymises the account."},
}


async def get_setting(db: AsyncSession, key: str) -> Any:
    row = (await db.execute(select(PlatformSettings.value).where(PlatformSettings.key == key))).scalar_one_or_none()
    if row is not None:
        return row
    if key in DEFAULT_SETTINGS:
        return DEFAULT_SETTINGS[key]["value"]
    raise KeyError(key)


async def list_settings(db: AsyncSession) -> list[dict]:
    stored = {s.key: s for s in (await db.execute(select(PlatformSettings))).scalars().all()}
    result = []
    for key, meta in DEFAULT_SETTINGS.items():
        row = stored.get(key)
        result.append({
            "key": key,
            "value": row.value if row else meta["value"],
            "version": row.version if row else 0,
            "description": meta["description"],
            "updated_at": row.updated_at if row else None,
            "updated_by": row.updated_by if row else None,
        })
    return result


async def update_setting(db: AsyncSession, key: str, value: Any, actor_id: int, reason: str | None) -> dict:
    """Versioned update. The caller audits and commits."""
    if key not in DEFAULT_SETTINGS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown setting '{key}'.")
    default = DEFAULT_SETTINGS[key]["value"]
    if type(default) is not type(value) and not (isinstance(default, (int, float)) and isinstance(value, (int, float))):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Setting '{key}' expects a value of type {type(default).__name__}.",
        )
    row = (await db.execute(
        select(PlatformSettings).where(PlatformSettings.key == key).with_for_update()
    )).scalar_one_or_none()
    now = utcnow()
    before = row.value if row else default
    if row:
        row.value = value
        row.version += 1
        row.updated_by = actor_id
        row.updated_at = now
    else:
        row = PlatformSettings(
            key=key, value=value, version=1, description=DEFAULT_SETTINGS[key]["description"],
            updated_by=actor_id, updated_at=now,
        )
        db.add(row)
    db.add(PlatformSettingsHistory(
        key=key, value=value, version=row.version, changed_by=actor_id, change_reason=reason, changed_at=now,
    ))
    return {"key": key, "before": before, "after": value, "version": row.version}
