"""Serialising listings for different audiences. Private fields are only included for the owner."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data_models.farmer_inventory_model import FarmerInventory, PRIVATE_LISTING_FIELDS
from src.data_models.listing_extras_model import ListingImages, ListingPriceTiers, ListingCertifications
from src.helpers.serializers import model_to_dict


def availability_type(listing: FarmerInventory) -> str:
    if listing.harvest_date and listing.harvest_date > date.today():
        return "pre_harvest"
    if listing.availability_date and listing.availability_date > date.today():
        return "scheduled"
    return "available_now"


def listing_dict(listing: FarmerInventory, viewer_id: int | None, **extra) -> dict:
    data = model_to_dict(listing)
    if viewer_id != listing.created_by:
        for field in PRIVATE_LISTING_FIELDS:
            data.pop(field, None)
    data["available_quantity"] = data.get("weight_kg")
    data["asking_price"] = data.get("proposed_cost")
    data["availability_type"] = availability_type(listing)
    data["is_pre_harvest"] = data["availability_type"] == "pre_harvest"
    data["delivery_options"] = [o for o in (listing.delivery_options or "").split(",") if o]
    data["price_label"] = "asking price (final price is negotiated)"
    data.update(extra)
    return data


async def images_for(db: AsyncSession, listing_ids) -> dict[int, list[dict]]:
    listing_ids = list(listing_ids)
    if not listing_ids:
        return {}
    rows = (await db.execute(
        select(ListingImages).where(ListingImages.listing_id.in_(listing_ids))
        .order_by(ListingImages.listing_id, ListingImages.sort_order, ListingImages.id)
    )).scalars().all()
    result: dict[int, list[dict]] = {}
    for row in rows:
        result.setdefault(row.listing_id, []).append(
            {"image_id": row.id, "file_id": row.file_id, "url": f"/api/files/{row.file_id}", "sort_order": row.sort_order}
        )
    return result


async def tiers_for(db: AsyncSession, listing_id: int) -> list[dict]:
    rows = (await db.execute(
        select(ListingPriceTiers).where(ListingPriceTiers.listing_id == listing_id)
        .order_by(ListingPriceTiers.min_quantity)
    )).scalars().all()
    return [{"min_quantity": r.min_quantity, "price_per_unit": r.price_per_unit} for r in rows]


async def certifications_for(db: AsyncSession, listing_id: int, include_unverified: bool) -> list[dict]:
    stmt = select(ListingCertifications).where(ListingCertifications.listing_id == listing_id)
    if not include_unverified:
        stmt = stmt.where(ListingCertifications.status == "verified")
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {"id": r.id, "cert_type": r.cert_type, "issuer": r.issuer, "status": r.status, "valid_until": r.valid_until,
         "file_url": f"/api/files/{r.file_id}" if r.file_id else None}
        for r in rows
    ]
