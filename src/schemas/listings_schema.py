from datetime import date
from typing import Optional, Literal
from pydantic import BaseModel, Field, field_validator

DeliveryOption = Literal["pickup", "farmer_delivery", "vendor_transport", "third_party"]


class PriceTierSchema(BaseModel):
    min_quantity: float = Field(..., gt=0)
    price_per_unit: float = Field(..., gt=0)


class ListingCreateSchema(BaseModel):
    crop: int
    variety: Optional[str] = Field(None, max_length=60)
    quantity: float = Field(..., ge=0, description="Available quantity in `unit` (expected quantity for pre-harvest).")
    unit: str = Field("kg", max_length=20)
    asking_price: float = Field(..., gt=0, description="Asking price per unit.")
    min_order_qty: Optional[float] = Field(None, gt=0)
    min_acceptable_price: Optional[float] = Field(None, gt=0, description="Private bargaining floor - never shown to vendors.")
    quality_grade: Optional[str] = Field(None, max_length=10)
    harvest_date: Optional[date] = None
    available_until: Optional[date] = None
    availability_date: Optional[date] = None
    packaging: Optional[Literal["loose", "bags", "crates", "boxes", "other"]] = None
    description: Optional[str] = Field(None, max_length=500)
    batch_code: Optional[str] = Field(None, max_length=40)
    organic_claim: bool = False
    delivery_options: list[DeliveryOption] = Field(default_factory=lambda: ["pickup"])
    low_stock_threshold: Optional[float] = Field(None, ge=0)
    image_file_ids: list[str] = Field(default_factory=list, max_length=10)
    price_tiers: list[PriceTierSchema] = Field(default_factory=list, max_length=10)
    publish: bool = True  # false = save as draft
    fertilizer: Optional[int] = None
    soil: Optional[int] = None


class ListingUpdateSchema(BaseModel):
    variety: Optional[str] = Field(None, max_length=60)
    quantity: Optional[float] = Field(None, ge=0)
    asking_price: Optional[float] = Field(None, gt=0)
    min_order_qty: Optional[float] = Field(None, gt=0)
    min_acceptable_price: Optional[float] = Field(None, gt=0)
    clear_min_acceptable_price: bool = False
    quality_grade: Optional[str] = Field(None, max_length=10)
    harvest_date: Optional[date] = None
    available_until: Optional[date] = None
    availability_date: Optional[date] = None
    packaging: Optional[Literal["loose", "bags", "crates", "boxes", "other"]] = None
    description: Optional[str] = Field(None, max_length=500)
    batch_code: Optional[str] = Field(None, max_length=40)
    organic_claim: Optional[bool] = None
    delivery_options: Optional[list[DeliveryOption]] = None
    low_stock_threshold: Optional[float] = Field(None, ge=0)


class ListingImagesSchema(BaseModel):
    file_ids: list[str] = Field(..., min_length=1, max_length=10)


class ListingPriceTiersSchema(BaseModel):
    tiers: list[PriceTierSchema] = Field(default_factory=list, max_length=10)


class CertificationSchema(BaseModel):
    cert_type: Literal["organic", "lab_test", "inspection", "other"]
    issuer: str = Field(..., max_length=120)
    file_id: str
    valid_until: Optional[date] = None


class StockUpdateSchema(BaseModel):
    quantity: float = Field(..., ge=0)
    note: Optional[str] = Field(None, max_length=255)


class MarketFilters(BaseModel):
    """Query parameters for market search. All optional; omit page_size to get every match."""
    q: Optional[str] = Field(None, max_length=100, description="Search produce name, variety or description.")
    crop_id: Optional[int] = None
    category_id: Optional[int] = None
    variety: Optional[str] = None
    state_id: Optional[int] = None
    district_id: Optional[int] = None
    farmer_id: Optional[int] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_quantity: Optional[float] = Field(None, description="Only listings with at least this much available.")
    order_quantity: Optional[float] = Field(None, description="Quantity you want: hides listings whose minimum order is larger.")
    unit: Optional[str] = None
    quality_grade: Optional[str] = None
    harvested_after: Optional[date] = None
    available_by: Optional[date] = Field(None, description="Produce can be supplied on or before this date.")
    pre_harvest: Optional[bool] = None
    verified_farmers_only: bool = False
    organic_verified_only: bool = False
    delivery_option: Optional[str] = None
    search: Optional[str] = None  # legacy alias of q
    sort_by: Literal[
        "newest", "price_asc", "price_desc", "quantity_desc", "harvest_desc", "harvest_asc",
        "rating_desc", "best_match",
    ] = "newest"
    page: int = Field(1, ge=1)
    page_size: Optional[int] = Field(None, ge=1, le=100)

    @field_validator("quality_grade")
    @classmethod
    def upper_grade(cls, v):
        return v.upper() if v else v
