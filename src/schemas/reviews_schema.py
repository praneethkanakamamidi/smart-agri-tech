from pydantic import BaseModel, Field
from typing import Optional


class CreateReviewSchema(BaseModel):
    order_id: int
    rating: int = Field(..., ge=1, le=5, description="Overall rating")
    quality_rating: Optional[int] = Field(None, ge=1, le=5, description="Produce quality (vendor rating a farmer)")
    communication_rating: Optional[int] = Field(None, ge=1, le=5)
    reliability_rating: Optional[int] = Field(None, ge=1, le=5, description="Fulfilment / payment reliability")
    quantity_accuracy_rating: Optional[int] = Field(None, ge=1, le=5, description="Vendor rating a farmer")
    comment: Optional[str] = Field(None, max_length=500)


class ReviewResponseSchema(BaseModel):
    response: str = Field(..., min_length=1, max_length=500)


class ModerateReviewSchema(BaseModel):
    hidden: bool
    reason: str = Field(..., min_length=3, max_length=255)
