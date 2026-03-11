from pydantic import BaseModel
from typing import Optional


class CreateOfferSchema(BaseModel):
    """Vendor creates a bargain offer."""
    stock_id: int
    vendor_offer_price: float
    quantity_kg: float
    message: Optional[str] = None


class VendorCounterOfferSchema(BaseModel):
    """Vendor sends a new offer after farmer countered."""
    vendor_offer_price: float


class FarmerRespondSchema(BaseModel):
    """Farmer responds to an offer: accept, reject, or counter."""
    action: str  # accept | reject | counter
    counter_price: Optional[float] = None  # Required when action='counter'
