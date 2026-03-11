from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.services.market_offers_service import MarketOffersService
from src.db_connections.postgresql_conn import get_db
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
def create_offer(
    payload: CreateOfferSchema,
    db: Session = Depends(get_db),
    service: MarketOffersService = Depends(market_offers_service),
    user: Users = Depends(get_current_active_user),
):
    """Vendor creates a bargain offer on a farmer's market listing."""
    return service.create_offer(payload, user.id, db)


@router.get("/market/offers/farmer/{farmer_id}")
def get_farmer_offers(
    farmer_id: int,
    db: Session = Depends(get_db),
    service: MarketOffersService = Depends(market_offers_service),
    user: Users = Depends(get_current_active_user),
):
    """Get all offers received by a farmer on their listings. Farmer can only view their own offers."""
    if user.id != farmer_id:
        raise HTTPException(status_code=403, detail="You can only view your own offers.")
    return service.get_farmer_offers(farmer_id, db)


@router.get("/market/offers/vendor/{vendor_id}")
def get_vendor_offers(
    vendor_id: int,
    db: Session = Depends(get_db),
    service: MarketOffersService = Depends(market_offers_service),
    user: Users = Depends(get_current_active_user),
):
    """Get all offers made by a vendor. Vendor can only view their own offers."""
    if user.id != vendor_id:
        raise HTTPException(status_code=403, detail="You can only view your own offers.")
    return service.get_vendor_offers(vendor_id, db)


@router.put("/market/offers/{offer_id}/farmer-respond")
def farmer_respond(
    offer_id: int,
    payload: FarmerRespondSchema,
    db: Session = Depends(get_db),
    service: MarketOffersService = Depends(market_offers_service),
    user: Users = Depends(get_current_active_user),
):
    """Farmer responds to an offer: accept, reject, or counter."""
    return service.farmer_respond(offer_id, user.id, payload, db)


@router.put("/market/offers/{offer_id}/vendor-accept")
def vendor_accept(
    offer_id: int,
    db: Session = Depends(get_db),
    service: MarketOffersService = Depends(market_offers_service),
    user: Users = Depends(get_current_active_user),
):
    """Vendor accepts farmer's counter offer (when status=countered)."""
    return service.vendor_accept(offer_id, user.id, db)


@router.put("/market/offers/{offer_id}/vendor-counter")
def vendor_counter(
    offer_id: int,
    payload: VendorCounterOfferSchema,
    db: Session = Depends(get_db),
    service: MarketOffersService = Depends(market_offers_service),
    user: Users = Depends(get_current_active_user),
):
    """Vendor sends a new offer after farmer countered."""
    return service.vendor_counter(offer_id, user.id, payload, db)
