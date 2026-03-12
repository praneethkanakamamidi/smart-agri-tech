from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.market_offers_service import MarketOffersService
from src.db_connections.database import get_db_async
from src.services.login_service import LoginService
from src.data_models.users_model import Users
from src.schemas.market_offers_schema import (
    CreateOfferSchema,
    FarmerRespondSchema,
    VendorCounterOfferSchema,
)

router = APIRouter(prefix="/api", tags=["Market Offers"])

get_current_active_user = LoginService.get_current_active_user


def market_offers_service() -> MarketOffersService:
    return MarketOffersService()


@router.post("/market/offers")
async def create_offer(
    payload: CreateOfferSchema,
    db: AsyncSession = Depends(get_db_async),
    service: MarketOffersService = Depends(market_offers_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.create_offer(payload, user.id, db)


@router.get("/market/offers/farmer/{farmer_id}")
async def get_farmer_offers(
    farmer_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: MarketOffersService = Depends(market_offers_service),
    user: Users = Depends(get_current_active_user),
):
    if user.id != farmer_id:
        raise HTTPException(status_code=403, detail="You can only view your own offers.")
    return await service.get_farmer_offers(farmer_id, db)


@router.get("/market/offers/vendor/{vendor_id}")
async def get_vendor_offers(
    vendor_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: MarketOffersService = Depends(market_offers_service),
    user: Users = Depends(get_current_active_user),
):
    if user.id != vendor_id:
        raise HTTPException(status_code=403, detail="You can only view your own offers.")
    return await service.get_vendor_offers(vendor_id, db)


@router.put("/market/offers/{offer_id}/farmer-respond")
async def farmer_respond(
    offer_id: int,
    payload: FarmerRespondSchema,
    db: AsyncSession = Depends(get_db_async),
    service: MarketOffersService = Depends(market_offers_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.farmer_respond(offer_id, user.id, payload, db)


@router.put("/market/offers/{offer_id}/vendor-accept")
async def vendor_accept(
    offer_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: MarketOffersService = Depends(market_offers_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.vendor_accept(offer_id, user.id, db)


@router.put("/market/offers/{offer_id}/vendor-counter")
async def vendor_counter(
    offer_id: int,
    payload: VendorCounterOfferSchema,
    db: AsyncSession = Depends(get_db_async),
    service: MarketOffersService = Depends(market_offers_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.vendor_counter(offer_id, user.id, payload, db)
