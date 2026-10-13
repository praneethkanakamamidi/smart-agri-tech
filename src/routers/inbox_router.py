from typing import Optional

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.realtime import manager
from src.data_models.users_model import Users
from src.db_connections.database import get_db_async, AsyncSessionLocal
from src.schemas.inbox_schema import SendMessageSchema, ReportSchema
from src.services.inbox_service import InboxService
from src.services.login_service import LoginService

router = APIRouter(prefix="/api", tags=["Inbox"])

get_current_active_user = LoginService.get_current_active_user


def inbox_service() -> InboxService:
    return InboxService()


@router.post("/inbox/messages")
async def send_message(
    payload: SendMessageSchema,
    db: AsyncSession = Depends(get_db_async),
    service: InboxService = Depends(inbox_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.send_message(payload, user.id, db)


@router.get("/inbox/conversations")
async def get_conversations(
    db: AsyncSession = Depends(get_db_async),
    service: InboxService = Depends(inbox_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.get_conversations(user.id, db)


@router.get("/inbox/conversations/{other_user_id}")
async def get_thread(
    other_user_id: int,
    negotiation_id: Optional[int] = None,
    order_id: Optional[int] = None,
    listing_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_async),
    service: InboxService = Depends(inbox_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.get_thread(user.id, other_user_id, db, page, page_size, negotiation_id, order_id, listing_id)


@router.get("/inbox/unread-count")
async def unread_count(
    db: AsyncSession = Depends(get_db_async),
    service: InboxService = Depends(inbox_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.unread_count(user.id, db)


@router.post("/users/{user_id}/block")
async def block_user(
    user_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: InboxService = Depends(inbox_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.block(user.id, user_id, db)


@router.delete("/users/{user_id}/block")
async def unblock_user(
    user_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: InboxService = Depends(inbox_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.unblock(user.id, user_id, db)


@router.post("/reports")
async def report(
    payload: ReportSchema,
    db: AsyncSession = Depends(get_db_async),
    service: InboxService = Depends(inbox_service),
    user: Users = Depends(get_current_active_user),
):
    """Report a user, listing, review or message for moderation."""
    return await service.report(user.id, payload, db)


@router.websocket("/ws")
async def realtime(websocket: WebSocket, token: str):
    """
    Live events: new messages, read receipts, notifications and negotiation updates.
    Connect with ws://host/api/ws?token=<access token>.
    """
    async with AsyncSessionLocal() as db:
        try:
            user = await LoginService.user_from_token(token, db)
        except Exception:
            await websocket.close(code=4401)
            return
    await manager.connect(user.id, websocket)
    try:
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_json({"event": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(user.id, websocket)
