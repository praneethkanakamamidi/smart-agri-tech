from typing import Optional, Literal
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.disputes_service import DisputesService
from src.db_connections.database import get_db_async
from src.data_models.users_model import Users
from src.schemas.disputes_schema import (
    RaiseDisputeSchema, ResolveDisputeSchema, DisputeMessageSchema, DisputeStatusSchema, AssignDisputeSchema,
)
from src.security_utils.role_guard import require_roles, current_user_with_role, ADMIN, FARMER, VENDOR

router = APIRouter(prefix="/api", tags=["Disputes"])

parties = require_roles(FARMER, VENDOR)
admin_only = require_roles(ADMIN)


def disputes_service() -> DisputesService:
    return DisputesService()


@router.post("/disputes")
async def raise_dispute(
    payload: RaiseDisputeSchema,
    db: AsyncSession = Depends(get_db_async),
    service: DisputesService = Depends(disputes_service),
    user: Users = Depends(parties),
):
    return await service.raise_dispute(payload, user.id, db)


@router.get("/disputes/mine")
async def list_my_disputes(
    db: AsyncSession = Depends(get_db_async),
    service: DisputesService = Depends(disputes_service),
    user: Users = Depends(parties),
):
    return await service.list_my_disputes(user.id, db)


@router.get("/disputes/{dispute_id}")
async def get_dispute(
    dispute_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: DisputesService = Depends(disputes_service),
    user: Users = Depends(current_user_with_role),
):
    """Case details and full history (responses, evidence, status changes)."""
    return await service.get(dispute_id, user.id, user.role_name == ADMIN, db)


@router.post("/disputes/{dispute_id}/messages")
async def add_dispute_message(
    dispute_id: int,
    payload: DisputeMessageSchema,
    db: AsyncSession = Depends(get_db_async),
    service: DisputesService = Depends(disputes_service),
    user: Users = Depends(current_user_with_role),
):
    """Respond or add evidence (upload files with purpose=dispute_evidence first)."""
    return await service.add_message(dispute_id, payload, user.id, user.role_name == ADMIN, db)


@router.post("/disputes/{dispute_id}/withdraw")
async def withdraw_dispute(
    dispute_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: DisputesService = Depends(disputes_service),
    user: Users = Depends(parties),
):
    return await service.withdraw(dispute_id, user.id, db)


@router.post("/disputes/{dispute_id}/escalate")
async def escalate_dispute(
    dispute_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: DisputesService = Depends(disputes_service),
    user: Users = Depends(parties),
):
    return await service.escalate(dispute_id, user.id, db)


@router.get("/admin/disputes")
async def list_all_disputes(
    status: Optional[Literal["open", "under_review", "awaiting_evidence", "resolved", "rejected", "withdrawn"]] = None,
    escalated: Optional[bool] = None,
    assigned_to: Optional[int] = None,
    db: AsyncSession = Depends(get_db_async),
    service: DisputesService = Depends(disputes_service),
    user: Users = Depends(admin_only),
):
    return await service.list_all_disputes(db, status, escalated, assigned_to)


@router.put("/admin/disputes/{dispute_id}/assign")
async def assign_dispute(
    dispute_id: int,
    payload: AssignDisputeSchema,
    db: AsyncSession = Depends(get_db_async),
    service: DisputesService = Depends(disputes_service),
    user: Users = Depends(admin_only),
):
    return await service.assign(dispute_id, user.id, payload.admin_id, db)


@router.put("/admin/disputes/{dispute_id}/status")
async def set_dispute_status(
    dispute_id: int,
    payload: DisputeStatusSchema,
    db: AsyncSession = Depends(get_db_async),
    service: DisputesService = Depends(disputes_service),
    user: Users = Depends(admin_only),
):
    return await service.set_status(dispute_id, user.id, payload, db)


@router.put("/admin/disputes/{dispute_id}/resolve")
async def resolve_dispute(
    dispute_id: int,
    payload: ResolveDisputeSchema,
    db: AsyncSession = Depends(get_db_async),
    service: DisputesService = Depends(disputes_service),
    user: Users = Depends(admin_only),
):
    return await service.resolve_dispute(dispute_id, payload, user.id, db)
