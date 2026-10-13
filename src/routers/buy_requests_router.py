from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.buy_requests_service import BuyRequestsService
from src.db_connections.database import get_db_async
from src.data_models.users_model import Users
from src.schemas.buy_requests_schema import (
    CreateBuyRequestSchema, RespondBuyRequestSchema, InviteFarmersSchema, AcceptResponseSchema,
)
from src.security_utils.role_guard import require_roles, FARMER, VENDOR

router = APIRouter(prefix="/api", tags=["Procurement (Buy Requests)"])
vendor_only = require_roles(VENDOR)
farmer_only = require_roles(FARMER)


def buy_requests_service() -> BuyRequestsService:
    return BuyRequestsService()


# ---- Vendor ----

@router.post("/buy-requests")
async def create_buy_request(payload: CreateBuyRequestSchema, db: AsyncSession = Depends(get_db_async),
                             service: BuyRequestsService = Depends(buy_requests_service), user: Users = Depends(vendor_only)):
    """Post a procurement request (produce, quantity, quality, deadline) and optionally invite farmers to quote."""
    return await service.create_request(payload, user, db)


@router.get("/buy-requests/mine")
async def list_my_buy_requests(db: AsyncSession = Depends(get_db_async),
                               service: BuyRequestsService = Depends(buy_requests_service), user: Users = Depends(vendor_only)):
    return await service.list_my_requests(user.id, db)


@router.post("/buy-requests/{request_id}/invite")
async def invite_farmers(request_id: int, payload: InviteFarmersSchema, db: AsyncSession = Depends(get_db_async),
                         service: BuyRequestsService = Depends(buy_requests_service), user: Users = Depends(vendor_only)):
    return await service.invite(request_id, payload.farmer_ids, user, db)


@router.put("/buy-requests/{request_id}/close")
async def close_buy_request(request_id: int, db: AsyncSession = Depends(get_db_async),
                            service: BuyRequestsService = Depends(buy_requests_service), user: Users = Depends(vendor_only)):
    return await service.close_request(request_id, user.id, db)


@router.get("/buy-requests/{request_id}/responses")
async def compare_quotations(request_id: int, db: AsyncSession = Depends(get_db_async),
                             service: BuyRequestsService = Depends(buy_requests_service), user: Users = Depends(vendor_only)):
    """Compare quotations side by side (price, total, quality, farmer rating and completed orders)."""
    return await service.compare_responses(request_id, user.id, db)


@router.put("/buy-requests/responses/{response_id}/shortlist")
async def shortlist_response(response_id: int, shortlisted: bool = True, db: AsyncSession = Depends(get_db_async),
                             service: BuyRequestsService = Depends(buy_requests_service), user: Users = Depends(vendor_only)):
    return await service.shortlist(response_id, user.id, shortlisted, db)


@router.post("/buy-requests/responses/{response_id}/negotiate")
async def negotiate_response(response_id: int, db: AsyncSession = Depends(get_db_async),
                             service: BuyRequestsService = Depends(buy_requests_service), user: Users = Depends(vendor_only)):
    return await service.negotiate(response_id, user, db)


@router.put("/buy-requests/responses/{response_id}/accept")
async def accept_buy_request_response(response_id: int, payload: Optional[AcceptResponseSchema] = None,
                                      db: AsyncSession = Depends(get_db_async),
                                      service: BuyRequestsService = Depends(buy_requests_service),
                                      user: Users = Depends(vendor_only)):
    """Accept a quotation as-is. Accept several to split the procurement across farmers."""
    return await service.accept_response(response_id, user, payload, db)


@router.put("/buy-requests/responses/{response_id}/reject")
async def reject_buy_request_response(response_id: int, db: AsyncSession = Depends(get_db_async),
                                      service: BuyRequestsService = Depends(buy_requests_service),
                                      user: Users = Depends(vendor_only)):
    return await service.reject_response(response_id, user.id, db)


# ---- Farmer ----

@router.get("/buy-requests")
async def list_open_buy_requests(crop_id: Optional[int] = None, state_id: Optional[int] = None,
                                 district_id: Optional[int] = None, invited_only: bool = False,
                                 page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                                 db: AsyncSession = Depends(get_db_async),
                                 service: BuyRequestsService = Depends(buy_requests_service),
                                 user: Users = Depends(farmer_only)):
    return await service.list_open_requests(user, db, crop_id, state_id, district_id, invited_only, page, page_size)


@router.post("/buy-requests/{request_id}/responses")
async def respond_to_buy_request(request_id: int, payload: RespondBuyRequestSchema, db: AsyncSession = Depends(get_db_async),
                                 service: BuyRequestsService = Depends(buy_requests_service), user: Users = Depends(farmer_only)):
    return await service.respond(request_id, payload, user.id, db)


@router.get("/buy-requests/responses/mine")
async def list_my_buy_request_responses(db: AsyncSession = Depends(get_db_async),
                                        service: BuyRequestsService = Depends(buy_requests_service),
                                        user: Users = Depends(farmer_only)):
    return await service.list_my_responses(user.id, db)


@router.put("/buy-requests/responses/{response_id}/withdraw")
async def withdraw_buy_request_response(response_id: int, db: AsyncSession = Depends(get_db_async),
                                        service: BuyRequestsService = Depends(buy_requests_service),
                                        user: Users = Depends(farmer_only)):
    return await service.withdraw_response(response_id, user.id, db)
