from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.data_models.users_model import Users
from src.db_connections.database import get_db_async
from src.schemas.listings_schema import (
    ListingCreateSchema, ListingUpdateSchema, ListingImagesSchema, ListingPriceTiersSchema, CertificationSchema,
    StockUpdateSchema,
)
from src.security_utils.role_guard import require_roles, current_user_with_role, FARMER, VENDOR
from src.services.listings_service import ListingsService

router = APIRouter(prefix="/api", tags=["Listings"])

farmer_only = require_roles(FARMER)


class ImageOrderSchema(BaseModel):
    image_ids: list[int] = Field(..., min_length=1)


def listings_service() -> ListingsService:
    return ListingsService()


@router.post("/listings")
async def create_listing(
    payload: ListingCreateSchema,
    db: AsyncSession = Depends(get_db_async),
    service: ListingsService = Depends(listings_service),
    user: Users = Depends(farmer_only),
):
    return await service.create(user, payload, db)


@router.get("/listings/mine")
async def my_listings(
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db_async),
    service: ListingsService = Depends(listings_service),
    user: Users = Depends(farmer_only),
):
    """Your listings with views, inquiries, negotiations, orders and sold quantity."""
    return await service.my_listings(user, db, status)


@router.get("/listings/saved")
async def saved_listings(
    db: AsyncSession = Depends(get_db_async),
    service: ListingsService = Depends(listings_service),
    user: Users = Depends(require_roles(VENDOR)),
):
    return await service.saved(user, db)


@router.get("/listings/{listing_id}")
async def listing_detail(
    listing_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: ListingsService = Depends(listings_service),
    user: Users = Depends(current_user_with_role),
):
    return await service.detail(listing_id, user, db)


@router.put("/listings/{listing_id}")
async def update_listing(
    listing_id: int,
    payload: ListingUpdateSchema,
    db: AsyncSession = Depends(get_db_async),
    service: ListingsService = Depends(listings_service),
    user: Users = Depends(farmer_only),
):
    return await service.update(user, listing_id, payload, db)


@router.delete("/listings/{listing_id}")
async def delete_listing(
    listing_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: ListingsService = Depends(listings_service),
    user: Users = Depends(farmer_only),
):
    return await service.delete(user, listing_id, db)


@router.put("/listings/{listing_id}/stock")
async def update_stock(
    listing_id: int,
    payload: StockUpdateSchema,
    db: AsyncSession = Depends(get_db_async),
    service: ListingsService = Depends(listings_service),
    user: Users = Depends(farmer_only),
):
    return await service.set_stock(user, listing_id, payload.quantity, payload.note, db)


@router.get("/listings/{listing_id}/stock-history")
async def stock_history(
    listing_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: ListingsService = Depends(listings_service),
    user: Users = Depends(farmer_only),
):
    return await service.stock_history(user, listing_id, db)


@router.post("/listings/{listing_id}/publish")
async def publish_listing(
    listing_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: ListingsService = Depends(listings_service),
    user: Users = Depends(farmer_only),
):
    """Publish a draft or resume a paused listing."""
    return await service.change_status(user, listing_id, "publish", db)


@router.post("/listings/{listing_id}/pause")
async def pause_listing(
    listing_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: ListingsService = Depends(listings_service),
    user: Users = Depends(farmer_only),
):
    """Temporarily hide a listing (marks produce as temporarily unavailable)."""
    return await service.change_status(user, listing_id, "pause", db)


@router.post("/listings/{listing_id}/duplicate")
async def duplicate_listing(
    listing_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: ListingsService = Depends(listings_service),
    user: Users = Depends(farmer_only),
):
    return await service.duplicate(user, listing_id, db)


@router.post("/listings/{listing_id}/images")
async def add_images(
    listing_id: int,
    payload: ListingImagesSchema,
    db: AsyncSession = Depends(get_db_async),
    service: ListingsService = Depends(listings_service),
    user: Users = Depends(farmer_only),
):
    return await service.add_images(user, listing_id, payload.file_ids, db)


@router.put("/listings/{listing_id}/images/order")
async def reorder_images(
    listing_id: int,
    payload: ImageOrderSchema,
    db: AsyncSession = Depends(get_db_async),
    service: ListingsService = Depends(listings_service),
    user: Users = Depends(farmer_only),
):
    return await service.reorder_images(user, listing_id, payload.image_ids, db)


@router.delete("/listings/{listing_id}/images/{image_id}")
async def remove_image(
    listing_id: int,
    image_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: ListingsService = Depends(listings_service),
    user: Users = Depends(farmer_only),
):
    return await service.remove_image(user, listing_id, image_id, db)


@router.put("/listings/{listing_id}/price-tiers")
async def set_price_tiers(
    listing_id: int,
    payload: ListingPriceTiersSchema,
    db: AsyncSession = Depends(get_db_async),
    service: ListingsService = Depends(listings_service),
    user: Users = Depends(farmer_only),
):
    """Quantity discounts the farmer proposes (e.g. ₹22/kg from 500 kg). Vendors still negotiate."""
    return await service.set_price_tiers(user, listing_id, payload.tiers, db)


@router.post("/listings/{listing_id}/certifications")
async def add_certification(
    listing_id: int,
    payload: CertificationSchema,
    db: AsyncSession = Depends(get_db_async),
    service: ListingsService = Depends(listings_service),
    user: Users = Depends(farmer_only),
):
    return await service.add_certification(user, listing_id, payload, db)


@router.post("/listings/{listing_id}/save")
async def save_listing(
    listing_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: ListingsService = Depends(listings_service),
    user: Users = Depends(require_roles(VENDOR)),
):
    return await service.save(user, listing_id, db)


@router.delete("/listings/{listing_id}/save")
async def unsave_listing(
    listing_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: ListingsService = Depends(listings_service),
    user: Users = Depends(require_roles(VENDOR)),
):
    return await service.unsave(user, listing_id, db)
