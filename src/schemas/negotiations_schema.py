from datetime import date
from typing import Optional, Literal
from pydantic import BaseModel, Field

DeliveryPreference = Literal["pickup", "farmer_delivery", "vendor_transport", "third_party"]
PaymentTerms = Literal["full_advance", "partial_advance", "pay_before_dispatch", "pay_on_delivery", "cash_on_delivery"]


class OfferTermsSchema(BaseModel):
    quantity: float = Field(..., gt=0)
    unit_price: float = Field(..., gt=0)
    delivery_preference: Optional[DeliveryPreference] = None
    preferred_date: Optional[date] = None
    packaging: Optional[str] = Field(None, max_length=30)
    quality_spec: Optional[str] = Field(None, max_length=255)
    message: Optional[str] = Field(None, max_length=1000)
    expires_in_hours: Optional[int] = Field(None, ge=1, le=168)


class StartNegotiationSchema(OfferTermsSchema):
    listing_id: int
    draft: bool = False  # save without sending


class AcceptOfferSchema(BaseModel):
    offer_id: int = Field(..., description="The offer you are accepting (guards against accepting a changed offer).")
    payment_terms: Optional[PaymentTerms] = None
    delivery_instructions: Optional[str] = Field(None, max_length=1000)


class ReasonSchema(BaseModel):
    reason: Optional[str] = Field(None, max_length=255)
