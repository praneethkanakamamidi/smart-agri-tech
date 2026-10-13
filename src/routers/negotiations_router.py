from typing import Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.idempotency import run_idempotent
from src.data_models.users_model import Users
from src.db_connections.database import get_db_async
from src.schemas.negotiations_schema import StartNegotiationSchema, OfferTermsSchema, AcceptOfferSchema, ReasonSchema
from src.security_utils.role_guard import require_roles, FARMER, VENDOR
from src.services.negotiations_service import NegotiationsService

router = APIRouter(prefix="/api", tags=["Negotiations"])

parties = require_roles(FARMER, VENDOR)


class SendDraftSchema(BaseModel):
    expires_in_hours: Optional[int] = Field(None, ge=1, le=168)


def negotiations_service() -> NegotiationsService:
    return NegotiationsService()


@router.post("/negotiations")
async def start_negotiation(
    payload: StartNegotiationSchema,
    db: AsyncSession = Depends(get_db_async),
    service: NegotiationsService = Depends(negotiations_service),
    user: Users = Depends(require_roles(VENDOR)),
):
    """Vendor opens a negotiation on a listing with a first offer (or a draft with `draft: true`)."""
    return await service.start(user, payload, db)


@router.get("/negotiations")
async def list_negotiations(
    status: Optional[str] = None,
    listing_id: Optional[int] = None,
    crop_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db_async),
    service: NegotiationsService = Depends(negotiations_service),
    user: Users = Depends(parties),
):
    return await service.list_mine(user, db, status, listing_id, crop_id)


@router.get("/negotiations/compare")
async def compare_offers(
    crop_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: NegotiationsService = Depends(negotiations_service),
    user: Users = Depends(require_roles(VENDOR)),
):
    """Compare your active negotiations for one crop across farmers, cheapest current price first."""
    return await service.compare(user, crop_id, db)


@router.get("/negotiations/{negotiation_id}")
async def get_negotiation(
    negotiation_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: NegotiationsService = Depends(negotiations_service),
    user: Users = Depends(parties),
):
    """Full offer history and the currently actionable offer."""
    return await service.get(user, negotiation_id, db)


@router.post("/negotiations/{negotiation_id}/offers")
async def submit_offer(
    negotiation_id: int,
    payload: OfferTermsSchema,
    db: AsyncSession = Depends(get_db_async),
    service: NegotiationsService = Depends(negotiations_service),
    user: Users = Depends(parties),
):
    """Counter the offer sent to you, or send a new offer after one expired or was withdrawn."""
    return await service.submit_offer(user, negotiation_id, payload, db)


@router.post("/negotiations/{negotiation_id}/send")
async def send_draft(
    negotiation_id: int,
    payload: SendDraftSchema,
    db: AsyncSession = Depends(get_db_async),
    service: NegotiationsService = Depends(negotiations_service),
    user: Users = Depends(parties),
):
    return await service.send_draft(user, negotiation_id, payload, db)


@router.post("/negotiations/{negotiation_id}/accept")
async def accept_offer(
    negotiation_id: int,
    payload: AcceptOfferSchema,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db_async),
    service: NegotiationsService = Depends(negotiations_service),
    user: Users = Depends(parties),
):
    """Accept the current offer. Stock is reserved and an order is created atomically."""
    return await run_idempotent(
        db, idempotency_key, user.id, f"negotiation-accept:{negotiation_id}", payload.model_dump(),
        lambda: service.accept(user, negotiation_id, payload, db),
    )


@router.post("/negotiations/{negotiation_id}/reject")
async def reject_offer(
    negotiation_id: int,
    payload: ReasonSchema,
    db: AsyncSession = Depends(get_db_async),
    service: NegotiationsService = Depends(negotiations_service),
    user: Users = Depends(parties),
):
    return await service.reject(user, negotiation_id, payload.reason, db)


@router.post("/negotiations/{negotiation_id}/withdraw")
async def withdraw_offer(
    negotiation_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: NegotiationsService = Depends(negotiations_service),
    user: Users = Depends(parties),
):
    return await service.withdraw(user, negotiation_id, db)


@router.post("/negotiations/{negotiation_id}/cancel")
async def cancel_negotiation(
    negotiation_id: int,
    payload: ReasonSchema,
    db: AsyncSession = Depends(get_db_async),
    service: NegotiationsService = Depends(negotiations_service),
    user: Users = Depends(parties),
):
    return await service.cancel(user, negotiation_id, payload.reason, db)
