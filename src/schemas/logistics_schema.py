from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field


class ShipmentPlanSchema(BaseModel):
    pickup_date: Optional[date] = None
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    pickup_address: Optional[str] = Field(None, max_length=255)
    pickup_instructions: Optional[str] = Field(None, max_length=1000)
    delivery_address: Optional[str] = Field(None, max_length=255)
    delivery_contact_name: Optional[str] = Field(None, max_length=80)
    delivery_contact_phone: Optional[str] = Field(None, max_length=20)
    transporter_name: Optional[str] = Field(None, max_length=120)
    vehicle_number: Optional[str] = Field(None, max_length=30)


class DispatchSchema(BaseModel):
    proof_file_id: Optional[str] = None
    transporter_name: Optional[str] = Field(None, max_length=120)
    vehicle_number: Optional[str] = Field(None, max_length=30)
    note: Optional[str] = Field(None, max_length=255)


class DeliveryConfirmSchema(BaseModel):
    delivery_code: Optional[str] = Field(None, min_length=6, max_length=6)
    receiver_name: Optional[str] = Field(None, max_length=80)
    accepted_quantity: Optional[float] = Field(None, ge=0)
    quality_accepted: Optional[bool] = None
    proof_file_id: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=1000)


class DeliveryFailureSchema(BaseModel):
    reason: str = Field(..., min_length=3, max_length=255)


class RescheduleSchema(BaseModel):
    pickup_date: date
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
