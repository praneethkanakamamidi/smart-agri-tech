"""Request bodies of the legacy /api/inventory endpoints (new clients use listings_schema)."""
from pydantic import BaseModel
from datetime import date
from typing import Optional


class AddFarmerInventorySchema(BaseModel):
    crop: Optional[int] = None
    fertilizer: Optional[int] = None
    soil: Optional[int] = None
    weight_kg: Optional[float] = None
    proposed_cost: Optional[float] = None
    description: Optional[str] = None
    quality_grade: Optional[str] = None
    harvest_date: Optional[date] = None
    available_until: Optional[date] = None
    created_by: Optional[int] = None  # Ignored: the farmer is taken from the access token.


class UpdateFarmerInventorySchema(BaseModel):
    id: Optional[int] = None
    crop: Optional[int] = None
    fertilizer: Optional[int] = None
    soil: Optional[int] = None
    weight_kg: Optional[float] = None
    proposed_cost: Optional[float] = None
    description: Optional[str] = None
    quality_grade: Optional[str] = None
    harvest_date: Optional[date] = None
    available_until: Optional[date] = None
    updated_by: Optional[int] = None  # Ignored: the farmer is taken from the access token.
