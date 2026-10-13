from pydantic import BaseModel, Field
from typing import Optional, Literal


class SendMessageSchema(BaseModel):
    receiver_id: int
    body: str = Field("", max_length=1000)
    attachment_file_id: Optional[str] = None  # image/PDF uploaded with purpose=chat_attachment
    listing_id: Optional[int] = None
    negotiation_id: Optional[int] = None
    order_id: Optional[int] = None
    dispute_id: Optional[int] = None
    offer_id: Optional[int] = None  # legacy market_offers id


class ReportSchema(BaseModel):
    target_type: Literal["user", "listing", "review", "message"]
    target_id: int
    reason: Literal["spam", "harassment", "fraud", "misleading", "prohibited_product", "abusive_review", "other"]
    details: Optional[str] = Field(None, max_length=1000)
