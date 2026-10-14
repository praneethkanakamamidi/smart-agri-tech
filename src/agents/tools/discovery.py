"""Read tools: discovery, listings, inventory, market prices."""
from datetime import date
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.config import settings
from src.agents.context import RunContext
from src.agents.retrieval import geo
from src.agents.retrieval.catalog import resolve_commodities
from src.agents.retrieval.search import SearchRequest, hybrid_search, nearby_suppliers, vendor_demand
from src.agents.tools.base import tool
from src.core.money import D
from src.data_models.crops_model import Crops
from src.data_models.districts_model import Districts
from src.data_models.farmer_inventory_model import FarmerInventory, ACTIVE
from src.data_models.profiles_model import FarmerProfiles, VendorProfiles
from src.data_models.users_model import Users, VERIFIED
from src.security_utils.role_guard import ADMIN, FARMER, VENDOR
from src.services.insights_service import InsightsService
from src.services.listing_views import images_for, listing_dict

DeliveryOption = Literal["pickup", "farmer_delivery", "vendor_transport", "third_party"]


async def my_location(db: AsyncSession, user: Users) -> tuple[float, float] | None:
    model = VendorProfiles if user.role_name == VENDOR else FarmerProfiles if user.role_name == FARMER else None
    if model is None:
        return None
    row = (await db.execute(select(model.latitude, model.longitude).where(model.user_id == user.id))).first()
    if row and geo.valid_coordinates(row[0], row[1]):
        return float(row[0]), float(row[1])
    return None


async def _crop_ids(db: AsyncSession, crop_ids: list[int], terms: list[str]) -> tuple[list[int], list[dict]]:
    resolved = await resolve_commodities(db, terms)
    return list(dict.fromkeys([*crop_ids, *(r["crop_id"] for r in resolved)])), resolved


class SearchListingsInput(BaseModel):
    query: str = Field("", max_length=300, description="Free-text description of the produce wanted.")
    crop_ids: list[int] = Field(default_factory=list, max_length=10)
    commodity_terms: list[str] = Field(default_factory=list, max_length=5)
    quantity: float | None = Field(None, gt=0)
    unit: str | None = Field(None, max_length=20)
    allow_partial: bool = False
    max_price: float | None = Field(None, gt=0)
    target_price: float | None = Field(None, gt=0)
    quality_grades: list[str] = Field(default_factory=list, max_length=3)
    available_by: date | None = None
    delivery_option: DeliveryOption | None = None
    radius_km: float | None = Field(None, gt=0, le=1000)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    use_my_location: bool = True
    organic_verified_only: bool = False
    verified_farmers_only: bool = False
    limit: int = Field(10, ge=1, le=50)


@tool("search_listings", SearchListingsInput,
      "Find live listings matching a buyer's need: hard filters, PostGIS radius, hybrid lexical+semantic ranking.")
async def search_listings(db: AsyncSession, actor: Users, args: SearchListingsInput, ctx: RunContext) -> dict:
    crop_ids, resolved = await _crop_ids(db, args.crop_ids, args.commodity_terms)
    notes = []
    unresolved = [t for t in args.commodity_terms if t not in {r["matched_term"] for r in resolved}]
    if unresolved:
        notes.append(f"Not in the catalogue, used as search words only: {', '.join(unresolved)}")
    origin, origin_source = None, None
    if geo.valid_coordinates(args.latitude, args.longitude):
        origin, origin_source = (args.latitude, args.longitude), "explicit"
    elif args.use_my_location:
        origin = await my_location(db, actor)
        origin_source = "profile" if origin else None
    radius = args.radius_km or (settings().default_radius_km if origin else None)
    if args.radius_km and not origin:
        notes.append("A radius was requested but no location is known; add coordinates to your profile.")
    query_words = " ".join([args.query, *unresolved]).strip()
    request = SearchRequest(
        query_text=query_words, crop_ids=crop_ids, quantity=D(args.quantity) if args.quantity else None,
        unit=args.unit, allow_partial=args.allow_partial, max_price=D(args.max_price) if args.max_price else None,
        target_price=D(args.target_price) if args.target_price else None, quality_grades=args.quality_grades,
        available_by=args.available_by, delivery_option=args.delivery_option,
        origin_lat=origin[0] if origin else None, origin_lon=origin[1] if origin else None,
        radius_km=radius if origin else None, organic_verified_only=args.organic_verified_only,
        verified_farmers_only=args.verified_farmers_only, limit=args.limit,
    )
    result = await hybrid_search(db, actor.id, request)
    if args.max_price:
        notes.append("Listings above your maximum are kept when everything else fits: asking prices are negotiable.")
    return {
        **result,
        "resolved_commodities": resolved,
        "applied_filters": {
            "crop_ids": crop_ids, "quantity": args.quantity, "unit": args.unit, "allow_partial": args.allow_partial,
            "quality_grades": args.quality_grades, "available_by": args.available_by,
            "delivery_option": args.delivery_option, "radius_km": radius if origin else None,
            "origin": origin_source, "organic_verified_only": args.organic_verified_only,
            "verified_farmers_only": args.verified_farmers_only,
        },
        "notes": notes,
    }


class ListingRef(BaseModel):
    listing_id: int = Field(..., gt=0)


@tool("get_listing_details", ListingRef, "Details of one listing (private fields only for its owner).")
async def get_listing_details(db: AsyncSession, actor: Users, args: ListingRef, ctx: RunContext) -> dict:
    row = (await db.execute(
        select(FarmerInventory, Crops.crop_name, Users.first_name, Users.last_name, Users.verification_status,
               Districts.district_name)
        .join(Crops, FarmerInventory.crop == Crops.id)
        .join(Users, FarmerInventory.created_by == Users.id)
        .outerjoin(Districts, Users.district == Districts.id)
        .where(FarmerInventory.id == args.listing_id, FarmerInventory.deleted_at.is_(None))
    )).first()
    if not row:
        raise HTTPException(status_code=404, detail="Listing not found.")
    listing, crop_name, first, last, verification, district = row
    if listing.status != ACTIVE and listing.created_by != actor.id and actor.role_name != ADMIN:
        raise HTTPException(status_code=404, detail="Listing not found.")
    images = await images_for(db, [listing.id])
    return listing_dict(
        listing, actor.id, crop_name=crop_name, farmer_name=f"{first or ''} {last or ''}".strip(),
        farmer_verified=verification == VERIFIED, district=district, image_count=len(images.get(listing.id, [])),
    )


class InventoryInput(BaseModel):
    include_inactive: bool = False


@tool("get_inventory", InventoryInput, "The farmer's own listings with available, reserved and sold quantities.")
async def get_inventory(db: AsyncSession, actor: Users, args: InventoryInput, ctx: RunContext) -> dict:
    stmt = (select(FarmerInventory, Crops.crop_name).join(Crops, FarmerInventory.crop == Crops.id)
            .where(FarmerInventory.created_by == actor.id, FarmerInventory.deleted_at.is_(None))
            .order_by(FarmerInventory.created_at.desc()))
    if not args.include_inactive:
        stmt = stmt.where(FarmerInventory.status.in_(("active", "reserved", "paused", "draft")))
    rows = (await db.execute(stmt.limit(100))).all()
    return {"listings": [
        {"listing_id": listing.id, "crop_name": crop, "variety": listing.variety, "status": listing.status,
         "unit": listing.unit, "available": str(D(listing.weight_kg)), "reserved": str(D(listing.reserved_qty)),
         "sold": str(D(listing.sold_qty)), "asking_price": str(D(listing.proposed_cost)),
         "available_until": listing.available_until}
        for listing, crop in rows
    ]}


class NearbyInput(BaseModel):
    commodity_terms: list[str] = Field(default_factory=list, max_length=5)
    crop_ids: list[int] = Field(default_factory=list, max_length=10)
    radius_km: float = Field(50, gt=0, le=1000)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    limit: int = Field(20, ge=1, le=50)


@tool("search_nearby_suppliers", NearbyInput, "Farmers with live listings within a radius, nearest first (PostGIS).")
async def search_nearby_suppliers(db: AsyncSession, actor: Users, args: NearbyInput, ctx: RunContext) -> dict:
    crop_ids, resolved = await _crop_ids(db, args.crop_ids, args.commodity_terms)
    origin = (args.latitude, args.longitude) if geo.valid_coordinates(args.latitude, args.longitude) \
        else await my_location(db, actor)
    if not origin:
        raise HTTPException(status_code=422, detail="No location: pass coordinates or add them to your profile.")
    suppliers = await nearby_suppliers(db, actor.id, origin[0], origin[1], args.radius_km, crop_ids or None, args.limit)
    return {"suppliers": suppliers, "radius_km": args.radius_km, "resolved_commodities": resolved,
            "distance_note": "Straight-line (geodesic) distance from the farm location on the profile."}


class VendorDemandInput(BaseModel):
    listing_id: int | None = Field(None, gt=0)
    commodity_terms: list[str] = Field(default_factory=list, max_length=5)
    crop_ids: list[int] = Field(default_factory=list, max_length=10)
    asking_price: float | None = Field(None, gt=0)
    quantity: float | None = Field(None, gt=0)
    radius_km: float | None = Field(None, gt=0, le=1000)
    limit: int = Field(20, ge=1, le=50)


@tool("search_vendor_demand", VendorDemandInput, "Vendors whose open buy requests or alerts match the farmer's produce.")
async def search_vendor_demand(db: AsyncSession, actor: Users, args: VendorDemandInput, ctx: RunContext) -> dict:
    crop_ids, resolved = await _crop_ids(db, args.crop_ids, args.commodity_terms)
    asking, quantity = (D(args.asking_price) if args.asking_price else None), (D(args.quantity) if args.quantity else None)
    if args.listing_id:
        listing = (await db.execute(select(FarmerInventory).where(
            FarmerInventory.id == args.listing_id, FarmerInventory.created_by == actor.id,
            FarmerInventory.deleted_at.is_(None)))).scalar_one_or_none()
        if not listing:
            raise HTTPException(status_code=404, detail="Listing not found.")
        crop_ids = list(dict.fromkeys([listing.crop, *crop_ids]))
        asking = asking or D(listing.proposed_cost)
        quantity = quantity or D(listing.weight_kg)
    if not crop_ids:
        raise HTTPException(status_code=422, detail="Say which produce (or listing) to find buyers for.")
    origin = await my_location(db, actor)
    matches = await vendor_demand(db, actor.id, crop_ids, asking_price=asking, quantity=quantity,
                                  lat=origin[0] if origin else None, lon=origin[1] if origin else None,
                                  radius_km=args.radius_km or (settings().default_radius_km if origin else None),
                                  limit=args.limit)
    return {"matches": matches, "resolved_commodities": resolved, "crop_ids": crop_ids}


class MarketPriceInput(BaseModel):
    crop_id: int | None = Field(None, gt=0)
    commodity: str | None = Field(None, max_length=60)
    days: int = Field(30, ge=7, le=365)
    unit: str | None = Field(None, max_length=20)
    quality_grade: str | None = Field(None, max_length=10)
    state_id: int | None = None
    district_id: int | None = None


@tool("retrieve_market_price_data", MarketPriceInput,
      "Asking and negotiated prices from the platform's own records, with sample size and reliability.")
async def retrieve_market_price_data(db: AsyncSession, actor: Users, args: MarketPriceInput, ctx: RunContext) -> dict:
    crop_id = args.crop_id
    if not crop_id and args.commodity:
        resolved = await resolve_commodities(db, [args.commodity])
        crop_id = resolved[0]["crop_id"] if resolved else None
    if not crop_id:
        raise HTTPException(status_code=404, detail="That produce isn't in the catalogue.")
    return await InsightsService().get_price_insights(
        crop_id, db, state_id=args.state_id, district_id=args.district_id, days=args.days,
        grade=args.quality_grade, unit=args.unit,
    )


class CommodityInput(BaseModel):
    terms: list[str] = Field(..., min_length=1, max_length=5)


@tool("resolve_commodity", CommodityInput, "Map produce names (any language) to catalogue crops.")
async def resolve_commodity(db: AsyncSession, actor: Users, args: CommodityInput, ctx: RunContext) -> dict:
    return {"matches": await resolve_commodities(db, args.terms)}


class ParseRequestInput(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


@tool("parse_request_rules", ParseRequestInput,
      "Deterministic parse of a request (produce, quantity, price, grade, dates) used when no model is available.")
async def parse_request_rules(db: AsyncSession, actor: Users, args: ParseRequestInput, ctx: RunContext) -> dict:
    from src.services.assistant_service import AssistantService

    filters, notes = await AssistantService().parse_query(args.text, db)
    crop_names = []
    if filters.get("crop_id"):
        name = (await db.execute(select(Crops.crop_name).where(Crops.id == filters["crop_id"]))).scalar_one_or_none()
        crop_names = [name] if name else []
    if not crop_names:
        words = [w for w in args.text.replace(",", " ").split() if len(w) > 2][:20]
        crop_names = [m["crop_name"] for m in await resolve_commodities(db, words)][:3]
    return {"filters": filters, "notes": notes, "crop_names": crop_names}
