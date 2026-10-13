from pydantic import BaseModel, Field
from typing import Optional


class CreateCropAlertSchema(BaseModel):
    crop: int
    state: Optional[int] = None
    district: Optional[int] = None
    min_quantity_kg: Optional[float] = Field(None, gt=0)
    max_price_per_kg: Optional[float] = Field(None, gt=0)
