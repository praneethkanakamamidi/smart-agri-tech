from typing import Optional, Literal
from pydantic import BaseModel, Field


class CreatePayment(BaseModel):
    order_id: int
    purpose: Literal["auto", "full", "advance", "balance"] = "auto"
    currency: str = "INR"
    amount_paid: Optional[float] = None  # ignored: the amount is calculated on the server


class VerifyPayment(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class RecordManualPayment(BaseModel):
    """Farmer records money received outside the gateway (cash, UPI, bank transfer)."""
    amount: float = Field(..., gt=0)
    method: Literal["cash", "upi", "bank_transfer"] = "cash"
    reference: Optional[str] = Field(None, max_length=100)


class RefundSchema(BaseModel):
    amount: Optional[float] = Field(None, gt=0)
    reason: str = Field(..., min_length=3, max_length=255)


class MarkRefundedSchema(BaseModel):
    reference: str = Field(..., max_length=100)


class SettlementPayoutSchema(BaseModel):
    payout_reference: str = Field(..., max_length=100)
