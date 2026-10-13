from typing import Optional, Literal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.data_models.users_model import Users
from src.db_connections.database import get_db_async
from src.security_utils.role_guard import require_roles, current_user_with_role, ADMIN
from src.services.admin_service import active_announcements
from src.services.support_service import SupportService

router = APIRouter(prefix="/api", tags=["Support & Announcements"])


class TicketCreateSchema(BaseModel):
    subject: str = Field(..., min_length=3, max_length=150)
    category: Literal["account", "payment", "order", "listing", "technical", "other"]
    message: str = Field(..., min_length=3, max_length=5000)
    order_id: Optional[int] = None
    file_ids: list[str] = Field(default_factory=list, max_length=5)


class TicketReplySchema(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)
    file_ids: list[str] = Field(default_factory=list, max_length=5)
    internal: bool = False


class TicketUpdateSchema(BaseModel):
    status: Optional[Literal["open", "in_progress", "resolved", "closed"]] = None
    priority: Optional[Literal["low", "normal", "high", "urgent"]] = None
    assigned_to: Optional[int] = None


def support_service() -> SupportService:
    return SupportService()


@router.post("/support/tickets")
async def create_ticket(payload: TicketCreateSchema, db: AsyncSession = Depends(get_db_async),
                        service: SupportService = Depends(support_service), user: Users = Depends(current_user_with_role)):
    return await service.create(user, payload, db)


@router.get("/support/tickets")
async def my_tickets(db: AsyncSession = Depends(get_db_async), service: SupportService = Depends(support_service),
                     user: Users = Depends(current_user_with_role)):
    return await service.list_mine(user, db)


@router.get("/support/tickets/{ticket_id}")
async def ticket_detail(ticket_id: int, db: AsyncSession = Depends(get_db_async),
                        service: SupportService = Depends(support_service), user: Users = Depends(current_user_with_role)):
    return await service.detail(ticket_id, user, user.role_name == ADMIN, db)


@router.post("/support/tickets/{ticket_id}/messages")
async def reply_ticket(ticket_id: int, payload: TicketReplySchema, db: AsyncSession = Depends(get_db_async),
                       service: SupportService = Depends(support_service), user: Users = Depends(current_user_with_role)):
    return await service.reply(ticket_id, user, user.role_name == ADMIN, payload, db)


@router.get("/admin/support/tickets")
async def admin_tickets(status: Optional[str] = None, priority: Optional[str] = None, assigned_to: Optional[int] = None,
                        db: AsyncSession = Depends(get_db_async), service: SupportService = Depends(support_service),
                        user: Users = Depends(require_roles(ADMIN))):
    return await service.admin_list(db, status, priority, assigned_to)


@router.put("/admin/support/tickets/{ticket_id}")
async def admin_update_ticket(ticket_id: int, payload: TicketUpdateSchema, db: AsyncSession = Depends(get_db_async),
                              service: SupportService = Depends(support_service), user: Users = Depends(require_roles(ADMIN))):
    return await service.admin_update(ticket_id, user, payload, db)


@router.get("/announcements")
async def announcements(accept_language: Optional[str] = Header(None), db: AsyncSession = Depends(get_db_async),
                        user: Users = Depends(current_user_with_role)):
    """Active platform announcements for your role, in your language."""
    lang = (accept_language or user.preferred_language or "en")[:2]
    return await active_announcements(db, user.role_name, lang)
