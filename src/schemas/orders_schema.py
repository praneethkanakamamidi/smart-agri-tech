from datetime import date
from typing import Optional, Literal
from pydantic import BaseModel, Field

FulfillmentMode = Literal["pickup", "farmer_delivery", "vendor_transport", "third_party"]
PaymentTerms = Literal["full_advance", "partial_advance", "pay_before_dispatch", "pay_on_delivery", "cash_on_delivery"]


class DirectOrderSchema(BaseModel):
    """Buy at the farmer's asking price (or quantity-tier price). The farmer still has to confirm."""
    listing_id: int
    quantity: float = Field(..., gt=0)
    fulfillment_mode: Optional[FulfillmentMode] = None
    payment_terms: Optional[PaymentTerms] = None
    expected_delivery_date: Optional[date] = None
    delivery_instructions: Optional[str] = Field(None, max_length=1000)


class StatusChangeSchema(BaseModel):
    status: Literal["preparing", "ready_for_pickup", "in_transit", "delivered", "delivery_failed", "completed"]
    note: Optional[str] = Field(None, max_length=255)


class CancelSchema(BaseModel):
    reason: str = Field(..., min_length=3, max_length=255)


class ReorderSchema(BaseModel):
    quantity: Optional[float] = Field(None, gt=0)
    unit_price: Optional[float] = Field(None, gt=0, description="Defaults to the last agreed price.")
    message: Optional[str] = Field(None, max_length=1000)


# ---- legacy request bodies ----

class PostOrderSchema(BaseModel):
    stock_id: Optional[int] = None
    vendor: Optional[int] = None  # Ignored: the vendor is taken from the access token.
    quantity: Optional[float] = None


class UpdateOrderStatus(BaseModel):
    order_id: Optional[int] = None
    status: Optional[str] = None
    user_id: Optional[int] = None  # Ignored: the caller is taken from the access token.
