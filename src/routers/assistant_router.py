from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.data_models.users_model import Users
from src.db_connections.database import get_db_async
from src.security_utils.role_guard import require_roles, FARMER, VENDOR, ADMIN
from src.services.assistant_service import AssistantService

router = APIRouter(prefix="/api/assistant", tags=["Assistant"])


class TextSchema(BaseModel):
    text: str = Field(..., min_length=2, max_length=500)


def assistant_service() -> AssistantService:
    return AssistantService()


@router.post("/search")
async def natural_language_search(payload: TextSchema, db: AsyncSession = Depends(get_db_async),
                                  service: AssistantService = Depends(assistant_service),
                                  user: Users = Depends(require_roles(VENDOR, FARMER, ADMIN))):
    """e.g. "500 kg tomatoes good quality this week around ₹20/kg in Guntur" -> filters + real listings."""
    return await service.search(user, payload.text, db)


@router.post("/listing-draft")
async def listing_draft(payload: TextSchema, db: AsyncSession = Depends(get_db_async),
                        service: AssistantService = Depends(assistant_service), user: Users = Depends(require_roles(FARMER))):
    """Turn a plain sentence into listing fields for review. Nothing is created."""
    return await service.listing_draft(user, payload.text, db)


@router.get("/negotiations/{negotiation_id}/summary")
async def negotiation_summary(negotiation_id: int, db: AsyncSession = Depends(get_db_async),
                              service: AssistantService = Depends(assistant_service),
                              user: Users = Depends(require_roles(FARMER, VENDOR))):
    return await service.negotiation_summary(user, negotiation_id, db)


@router.get("/negotiations/{negotiation_id}/suggest-counter")
async def suggest_counter(negotiation_id: int, db: AsyncSession = Depends(get_db_async),
                          service: AssistantService = Depends(assistant_service),
                          user: Users = Depends(require_roles(FARMER, VENDOR))):
    """A counteroffer suggestion with its basis. It is never sent automatically."""
    return await service.suggest_counter(user, negotiation_id, db)


@router.get("/orders/summary")
async def orders_summary(db: AsyncSession = Depends(get_db_async), service: AssistantService = Depends(assistant_service),
                         user: Users = Depends(require_roles(FARMER, VENDOR))):
    return await service.orders_summary(user, db)


@router.get("/admin/summary")
async def admin_summary(db: AsyncSession = Depends(get_db_async), service: AssistantService = Depends(assistant_service),
                        user: Users = Depends(require_roles(ADMIN))):
    return await service.admin_summary(db)
