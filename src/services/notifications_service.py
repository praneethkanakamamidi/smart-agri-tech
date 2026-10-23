from fastapi import HTTPException, status
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, time as dtime

from src.core import channels
from src.core.i18n import render, normalize_language
from src.core.realtime import queue_event
from src.data_models.notifications_model import (
    Notifications, SECURITY, TRANSACTIONAL, REMINDER, PROMOTIONAL,
)
from src.data_models.platform_model import NotificationPreferences, NotificationDeliveries, DeviceTokens
from src.data_models.users_model import Users
from src.core.clock import utcnow

MAX_DELIVERY_ATTEMPTS = 5
# External channels used for each category (in-app is always used).
CATEGORY_CHANNELS = {
    SECURITY: ("email", "sms"),
    TRANSACTIONAL: ("email", "sms", "push"),
    REMINDER: ("push", "sms"),
    PROMOTIONAL: ("email", "push", "whatsapp"),
}


def _in_quiet_hours(now: dtime, start: dtime | None, end: dtime | None) -> bool:
    if not start or not end or start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end  # window crosses midnight


def _quiet_hours_end(now: datetime, end: dtime) -> datetime:
    candidate = now.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    return candidate if candidate > now else candidate + timedelta(days=1)


class NotificationsService:
    """In-app notifications plus queued delivery on email/SMS/push/WhatsApp."""

    @staticmethod
    def notify(
        db: AsyncSession,
        user_id: int,
        type: str,
        title: str,
        message: str = None,
        ref_type: str = None,
        ref_id: int = None,
    ):
        """Queue a plain in-app notification on the caller's session. The caller commits."""
        db.add(
            Notifications(
                user_id=user_id,
                type=type,
                title=title,
                message=message,
                ref_type=ref_type,
                ref_id=ref_id,
                is_read=False,
                category=TRANSACTIONAL,
                created_at=utcnow(),
            )
        )
        queue_event(db, user_id, {"event": "notification", "type": type, "title": title, "message": message,
                                  "ref_type": ref_type, "ref_id": ref_id})

    @staticmethod
    async def notify_user(
        db: AsyncSession,
        user_id: int,
        template: str,
        params: dict | None = None,
        ref_type: str = None,
        ref_id: int = None,
        category: str = TRANSACTIONAL,
        dedupe_key: str | None = None,
        notification_type: str | None = None,
    ) -> Notifications | None:
        """
        Localised notification for one user: renders the template in the user's language,
        honours preferences, quiet hours and dedupe, and queues external deliveries.
        The caller commits.
        """
        if dedupe_key:
            exists = (await db.execute(select(Notifications.id).where(
                Notifications.user_id == user_id, Notifications.dedupe_key == dedupe_key,
            ))).scalar_one_or_none()
            if exists:
                return None

        user = (await db.execute(select(Users).where(Users.id == user_id))).scalar_one_or_none()
        if not user or user.deleted_at:
            return None
        prefs = (await db.execute(
            select(NotificationPreferences).where(NotificationPreferences.user_id == user_id)
        )).scalar_one_or_none()
        if category == PROMOTIONAL and not (prefs and prefs.promotional_enabled):
            return None

        title, message = render(template, normalize_language(user.preferred_language), **(params or {}))
        now = utcnow()
        notification = Notifications(
            user_id=user_id, type=notification_type or template, title=title, message=message,
            ref_type=ref_type, ref_id=ref_id, is_read=False, category=category,
            dedupe_key=dedupe_key, created_at=now,
        )
        db.add(notification)
        await db.flush()

        enabled = {
            "email": prefs.email_enabled if prefs else True,
            "sms": prefs.sms_enabled if prefs else True,
            "push": prefs.push_enabled if prefs else True,
            "whatsapp": prefs.whatsapp_enabled if prefs else False,
        }
        if category == SECURITY:
            enabled["email"] = enabled["sms"] = True  # security messages can't be switched off
        defer_until = None
        if category in (REMINDER, PROMOTIONAL) and prefs and _in_quiet_hours(
            now.time(), prefs.quiet_hours_start, prefs.quiet_hours_end
        ):
            defer_until = _quiet_hours_end(now, prefs.quiet_hours_end)

        for channel in CATEGORY_CHANNELS.get(category, ()):
            if not enabled.get(channel):
                continue
            if channel == "email" and not (user.email and user.email_verified):
                continue
            if channel in ("sms", "whatsapp") and not (user.phone and user.phone_verified):
                continue
            db.add(NotificationDeliveries(
                notification_id=notification.id, channel=channel, status="pending", attempts=0,
                next_attempt_at=defer_until or now, created_at=now,
            ))

        queue_event(db, user_id, {
            "event": "notification", "id": notification.id, "type": notification.type, "title": title,
            "message": message, "ref_type": ref_type, "ref_id": ref_id,
        })
        return notification

    @staticmethod
    async def process_deliveries(db: AsyncSession, batch_size: int = 100) -> int:
        """Send due external deliveries with exponential backoff. Used by the scheduler."""
        now = utcnow()
        rows = (await db.execute(
            select(NotificationDeliveries, Notifications, Users)
            .join(Notifications, NotificationDeliveries.notification_id == Notifications.id)
            .join(Users, Notifications.user_id == Users.id)
            .where(NotificationDeliveries.status == "pending", NotificationDeliveries.next_attempt_at <= now)
            .order_by(NotificationDeliveries.id)
            .limit(batch_size)
            .with_for_update(of=NotificationDeliveries, skip_locked=True)
        )).all()
        for delivery, notification, user in rows:
            delivery.attempts += 1
            try:
                if delivery.channel == "email":
                    await channels.send("email", user.email, notification.title, notification.message or "")
                elif delivery.channel in ("sms", "whatsapp"):
                    await channels.send(delivery.channel, user.phone, notification.title, notification.message or "")
                elif delivery.channel == "push":
                    tokens = (await db.execute(
                        select(DeviceTokens.token).where(DeviceTokens.user_id == user.id)
                    )).scalars().all()
                    if not tokens:
                        delivery.status = "skipped"
                        delivery.last_error = "No registered device"
                        continue
                    for token in tokens:
                        await channels.send("push", token, notification.title, notification.message or "",
                                            {"ref_type": notification.ref_type, "ref_id": notification.ref_id})
                delivery.status = "sent"
                delivery.sent_at = utcnow()
                delivery.last_error = None
            except Exception as e:  # provider failures are recorded and retried
                delivery.last_error = str(e)[:255]
                if delivery.attempts >= MAX_DELIVERY_ATTEMPTS:
                    delivery.status = "failed"
                else:
                    delivery.next_attempt_at = utcnow() + timedelta(minutes=2 ** delivery.attempts)
        await db.commit()
        return len(rows)

    async def get_notifications(
        self, user_id: int, db: AsyncSession, unread_only: bool = False, page: int = 1, page_size: int = 20
    ):
        try:
            filters = [Notifications.user_id == user_id]
            if unread_only:
                filters.append(Notifications.is_read.is_(False))

            count_stmt = select(func.count(Notifications.id)).where(*filters)
            total_records = (await db.execute(count_stmt)).scalar() or 0

            stmt = (
                select(Notifications)
                .where(*filters)
                .order_by(Notifications.created_at.desc(), Notifications.id.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
            result = await db.execute(stmt)
            return {
                "page": page,
                "page_size": page_size,
                "total_records": total_records,
                "total_pages": (total_records + page_size - 1) // page_size,
                "data": result.scalars().all(),
            }
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def unread_count(self, user_id: int, db: AsyncSession):
        stmt = select(func.count(Notifications.id)).where(
            Notifications.user_id == user_id,
            Notifications.is_read.is_(False),
        )
        return {"unread_count": (await db.execute(stmt)).scalar() or 0}

    async def mark_read(self, notification_id: int, user_id: int, db: AsyncSession):
        try:
            stmt = select(Notifications).where(
                Notifications.id == notification_id,
                Notifications.user_id == user_id,
            )
            notification = (await db.execute(stmt)).scalar_one_or_none()
            if not notification:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Notification not found.",
                )
            notification.is_read = True
            await db.commit()
            return {"success": "Notification marked as read."}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def mark_all_read(self, user_id: int, db: AsyncSession):
        try:
            stmt = (
                update(Notifications)
                .where(Notifications.user_id == user_id, Notifications.is_read.is_(False))
                .values(is_read=True)
            )
            result = await db.execute(stmt)
            await db.commit()
            return {"success": f"{result.rowcount} notifications marked as read."}
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def get_preferences(self, user_id: int, db: AsyncSession) -> dict:
        prefs = (await db.execute(
            select(NotificationPreferences).where(NotificationPreferences.user_id == user_id)
        )).scalar_one_or_none()
        language = (await db.execute(select(Users.preferred_language).where(Users.id == user_id))).scalar_one()
        return {
            "email_enabled": prefs.email_enabled if prefs else True,
            "sms_enabled": prefs.sms_enabled if prefs else True,
            "push_enabled": prefs.push_enabled if prefs else True,
            "whatsapp_enabled": prefs.whatsapp_enabled if prefs else False,
            "promotional_enabled": prefs.promotional_enabled if prefs else False,
            "quiet_hours_start": prefs.quiet_hours_start if prefs else None,
            "quiet_hours_end": prefs.quiet_hours_end if prefs else None,
            "preferred_language": language,
            "note": "Security and transaction messages are always delivered in-app; security messages also ignore channel opt-outs.",
        }

    async def update_preferences(self, user_id: int, payload, db: AsyncSession) -> dict:
        prefs = (await db.execute(
            select(NotificationPreferences).where(NotificationPreferences.user_id == user_id)
        )).scalar_one_or_none()
        if not prefs:
            prefs = NotificationPreferences(user_id=user_id)
            db.add(prefs)
        for field in ("email_enabled", "sms_enabled", "push_enabled", "whatsapp_enabled",
                      "promotional_enabled", "quiet_hours_start", "quiet_hours_end"):
            value = getattr(payload, field)
            if value is not None:
                setattr(prefs, field, value)
        if payload.clear_quiet_hours:
            prefs.quiet_hours_start = prefs.quiet_hours_end = None
        prefs.updated_at = utcnow()
        if payload.preferred_language:
            user = (await db.execute(select(Users).where(Users.id == user_id))).scalar_one()
            user.preferred_language = normalize_language(payload.preferred_language)
        await db.commit()
        return await self.get_preferences(user_id, db)

    async def register_device(self, user_id: int, token: str, platform: str, db: AsyncSession) -> dict:
        existing = (await db.execute(select(DeviceTokens).where(DeviceTokens.token == token))).scalar_one_or_none()
        now = utcnow()
        if existing:
            existing.user_id = user_id
            existing.platform = platform
            existing.last_seen_at = now
        else:
            db.add(DeviceTokens(user_id=user_id, token=token, platform=platform, created_at=now, last_seen_at=now))
        await db.commit()
        return {"success": "Device registered for push notifications."}

    async def unregister_device(self, user_id: int, token: str, db: AsyncSession) -> dict:
        existing = (await db.execute(select(DeviceTokens).where(
            DeviceTokens.token == token, DeviceTokens.user_id == user_id
        ))).scalar_one_or_none()
        if existing:
            await db.delete(existing)
            await db.commit()
        return {"success": "Device unregistered."}


notify_user = NotificationsService.notify_user
