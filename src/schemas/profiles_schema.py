from typing import Optional, Literal
from pydantic import BaseModel, Field


class FarmerProfileSchema(BaseModel):
    farm_name: Optional[str] = Field(None, max_length=120)
    farm_address: Optional[str] = Field(None, max_length=255)
    village: Optional[str] = Field(None, max_length=80)
    pincode: Optional[str] = Field(None, max_length=10)
    state: Optional[int] = None
    district: Optional[int] = None
    produce_categories: Optional[list[int]] = None
    farming_type: Optional[Literal["conventional", "organic", "natural", "mixed"]] = None
    farm_size_acres: Optional[float] = Field(None, ge=0)
    harvest_schedule: Optional[str] = Field(None, max_length=2000)
    payout_method: Optional[Literal["bank", "upi"]] = None
    bank_account_holder: Optional[str] = Field(None, max_length=120)
    bank_account_number: Optional[str] = Field(None, min_length=6, max_length=20)
    bank_ifsc: Optional[str] = Field(None, pattern=r"^[A-Za-z]{4}0[A-Za-z0-9]{6}$")
    upi_id: Optional[str] = Field(None, pattern=r"^[\w.\-]{2,}@[A-Za-z]{2,}$")


class VendorProfileSchema(BaseModel):
    business_name: Optional[str] = Field(None, max_length=120)
    business_type: Optional[Literal["retailer", "wholesaler", "restaurant", "trader", "processor", "other"]] = None
    business_address: Optional[str] = Field(None, max_length=255)
    pincode: Optional[str] = Field(None, max_length=10)
    state: Optional[int] = None
    district: Optional[int] = None
    gstin: Optional[str] = Field(None, pattern=r"^[0-9A-Za-z]{15}$")
    purchase_categories: Optional[list[int]] = None
    typical_quantity: Optional[float] = Field(None, ge=0)
    typical_quantity_unit: Optional[str] = Field(None, max_length=20)
    billing_address: Optional[str] = Field(None, max_length=255)
    delivery_preference: Optional[Literal["pickup", "farmer_delivery", "vendor_transport", "third_party"]] = None
    payment_preference: Optional[Literal["full_advance", "partial_advance", "pay_before_dispatch", "pay_on_delivery", "cash_on_delivery"]] = None


class VerificationRequestSchema(BaseModel):
    verification_type: Literal["identity", "farm", "business"]
    document_type: str = Field(..., max_length=40)  # aadhaar | pan | land_record | gst_certificate | trade_licence ...
    document_number: Optional[str] = Field(None, max_length=40)
    file_ids: list[str] = Field(..., min_length=1, max_length=5)
