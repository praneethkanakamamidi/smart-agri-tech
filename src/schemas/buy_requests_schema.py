from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import date


class CreateBuyRequestSchema(BaseModel):
    crop: int
    quantity_kg: float = Field(..., gt=0, description="Required quantity in `unit`.")
    unit: str = Field("kg", max_length=20)
    max_price_per_kg: Optional[float] = Field(None, gt=0, description="Maximum price per unit.")
    quality_grade: Optional[str] = Field(None, max_length=10)
    quality_spec: Optional[str] = Field(None, max_length=255)
    packaging: Optional[str] = Field(None, max_length=30)
    state: Optional[int] = None
    district: Optional[int] = None
    needed_by: Optional[date] = None
    description: Optional[str] = Field(None, max_length=255)
    invite_farmer_ids: list[int] = Field(default_factory=list, max_length=50)


class InviteFarmersSchema(BaseModel):
    farmer_ids: list[int] = Field(..., min_length=1, max_length=50)


class RespondBuyRequestSchema(BaseModel):
    farmer_inventory: int  # The farmer's listing that will fulfil the request
    price_per_kg: float = Field(..., gt=0)
    quantity_kg: float = Field(..., gt=0)
    message: Optional[str] = Field(None, max_length=255)


class AcceptResponseSchema(BaseModel):
    payment_terms: Optional[Literal["full_advance", "partial_advance", "pay_before_dispatch", "pay_on_delivery", "cash_on_delivery"]] = None
    fulfillment_mode: Optional[Literal["pickup", "farmer_delivery", "vendor_transport", "third_party"]] = None
