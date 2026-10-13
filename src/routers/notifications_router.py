from datetime import time
from typing import Optional, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.notifications_service import NotificationsService
from src.db_connections.database import get_db_async
from src.services.login_service import LoginService
from src.data_models.users_model import Users

router = APIRouter(prefix="/api", tags=["Notifications"])

get_current_active_user = LoginService.get_current_active_user


class NotificationPreferencesSchema(BaseModel):
    email_enabled: Optional[bool] = None
    sms_enabled: Optional[bool] = None
    push_enabled: Optional[bool] = None
    whatsapp_enabled: Optional[bool] = None
    promotional_enabled: Optional[bool] = None
    quiet_hours_start: Optional[time] = None  # UTC
    quiet_hours_end: Optional[time] = None
    clear_quiet_hours: bool = False
    preferred_language: Optional[Literal["en", "te"]] = None


class DeviceTokenSchema(BaseModel):
    token: str = Field(..., min_length=10, max_length=512)
    platform: Literal["android", "ios", "web"] = "android"


def notifications_service() -> NotificationsService:
    return NotificationsService()


@router.get("/notifications")
async def get_notifications(
    unread_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_async),
    service: NotificationsService = Depends(notifications_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.get_notifications(user.id, db, unread_only, page, page_size)


@router.get("/notifications/unread-count")
async def unread_count(
    db: AsyncSession = Depends(get_db_async),
    service: NotificationsService = Depends(notifications_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.unread_count(user.id, db)


@router.put("/notifications/read-all")
async def mark_all_read(
    db: AsyncSession = Depends(get_db_async),
    service: NotificationsService = Depends(notifications_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.mark_all_read(user.id, db)


@router.get("/notifications/preferences")
async def get_preferences(
    db: AsyncSession = Depends(get_db_async),
    service: NotificationsService = Depends(notifications_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.get_preferences(user.id, db)


@router.put("/notifications/preferences")
async def update_preferences(
    payload: NotificationPreferencesSchema,
    db: AsyncSession = Depends(get_db_async),
    service: NotificationsService = Depends(notifications_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.update_preferences(user.id, payload, db)


@router.post("/notifications/devices")
async def register_device(
    payload: DeviceTokenSchema,
    db: AsyncSession = Depends(get_db_async),
    service: NotificationsService = Depends(notifications_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.register_device(user.id, payload.token, payload.platform, db)


@router.delete("/notifications/devices")
async def unregister_device(
    payload: DeviceTokenSchema,
    db: AsyncSession = Depends(get_db_async),
    service: NotificationsService = Depends(notifications_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.unregister_device(user.id, payload.token, db)


@router.put("/notifications/{notification_id}/read")
async def mark_read(
    notification_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: NotificationsService = Depends(notifications_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.mark_read(notification_id, user.id, db)
