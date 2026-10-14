"""
Hybrid supplier discovery.

  1. Hard filters in SQL: live listing (active, in stock, not expired, not deleted), commodity,
     quantity and minimum order, grade, availability date, delivery option, organic/verified,
     PostGIS radius, never the viewer's own listings, never blocked counterparties.
  2. Lexical retrieval: PostgreSQL full-text rank over the indexed listing text.
  3. Semantic retrieval: pgvector cosine similarity with the configured embedding model.
  4. Reciprocal rank fusion of 2 and 3 -> relevance; optional cross-encoder on the top N.
  5. Explainable business score (ranking.py) and a final availability re-check.

Only real listing rows are returned, with the actual price, quantity and PostGIS distance.
"""
import re
import time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, exists, func, null, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.config import settings
from src.agents.retrieval import geo
from src.agents.retrieval.embeddings import embed_queries, get_embedder, vector_literal
from src.agents.retrieval.indexer import index_listings
from src.agents.retrieval.ranking import Candidate, RankingRequest, normalise, rank, rrf
from src.core.money import D
from src.data_models.buy_requests_model import BuyRequests
from src.data_models.crop_alerts_model import CropAlerts
from src.data_models.crops_model import Crops
from src.data_models.districts_model import Districts
from src.data_models.farmer_inventory_model import FarmerInventory, ACTIVE
from src.data_models.platform_model import UserBlocks
from src.data_models.profiles_model import FarmerProfiles, VendorProfiles
from src.data_models.reviews_model import Reviews
from src.data_models.users_model import Users, VERIFIED
from src.services.trust_service import completed_counts

_STOPWORDS = {
    "i", "me", "my", "we", "need", "want", "looking", "for", "find", "get", "buy", "some", "of", "the", "a", "an",
    "and", "or", "in", "near", "around", "within", "km", "kg", "kgs", "quintal", "quintals", "tonne", "tonnes",
    "ton", "tons", "rs", "inr", "per", "under", "below", "above", "about", "please", "show", "me", "with", "to",
    "from", "this", "next", "week", "today", "tomorrow", "by", "at", "is", "are", "who", "can", "supply",
}


@dataclass
class SearchRequest:
    query_text: str = ""
    crop_ids: list[int] = field(default_factory=list)
    quantity: Decimal | None = None
    unit: str | None = None
    allow_partial: bool = False
    max_price: Decimal | None = None
    target_price: Decimal | None = None
    quality_grades: list[str] = field(default_factory=list)
    available_by: date | None = None
    delivery_option: str | None = None
    origin_lat: float | None = None
    origin_lon: float | None = None
    radius_km: float | None = None
    organic_verified_only: bool = False
    verified_farmers_only: bool = False
    limit: int | None = None


def lexical_query(text_value: str) -> str | None:
    """OR-of-prefixes tsquery from the meaningful words (numbers, units and filler removed)."""
    words = [w.lower() for w in re.findall(r"\w+", text_value or "", re.UNICODE)]
    terms = [w for w in words if w not in _STOPWORDS and not w.isdigit() and len(w) > 1]
    terms = list(dict.fromkeys(re.sub(r"[^\w]", "", t) for t in terms))[:12]
    return " | ".join(f"{t}:*" for t in terms if t) or None


def _blocked(viewer_id: int, other_col):
    return exists(select(UserBlocks.id).where(or_(
        and_(UserBlocks.blocker_id == viewer_id, UserBlocks.blocked_id == other_col),
        and_(UserBlocks.blocker_id == other_col, UserBlocks.blocked_id == viewer_id),
    )))


def _rating_subquery():
    return (
        select(Reviews.reviewee.label("user_id"), func.avg(Reviews.rating).label("avg_rating"),
               func.count(Reviews.id).label("review_count"))
        .where(Reviews.is_hidden.is_(False)).group_by(Reviews.reviewee).subquery()
    )


async def _hard_filtered(db: AsyncSession, viewer_id: int, req: SearchRequest) -> list[Candidate]:
    cfg = settings()
    today = date.today()
    rating = _rating_subquery()
    lat = func.coalesce(FarmerInventory.pickup_latitude, FarmerProfiles.latitude)
    lon = func.coalesce(FarmerInventory.pickup_longitude, FarmerProfiles.longitude)
    has_origin = geo.valid_coordinates(req.origin_lat, req.origin_lon)
    distance = geo.distance_km(geo.point(lat, lon), geo.origin(req.origin_lat, req.origin_lon)) if has_origin else None
    columns = [FarmerInventory, Crops.crop_name, Districts.district_name, Users.verification_status,
               rating.c.avg_rating, rating.c.review_count]
    stmt = (
        select(*columns, (distance if distance is not None else null()).label("distance_km"))
        .join(Users, FarmerInventory.created_by == Users.id)
        .join(Crops, FarmerInventory.crop == Crops.id)
        .outerjoin(FarmerProfiles, FarmerProfiles.user_id == FarmerInventory.created_by)
        .outerjoin(Districts, Users.district == Districts.id)
        .outerjoin(rating, rating.c.user_id == FarmerInventory.created_by)
        .where(
            FarmerInventory.status == ACTIVE, FarmerInventory.deleted_at.is_(None), FarmerInventory.weight_kg > 0,
            Users.deleted_at.is_(None), FarmerInventory.created_by != viewer_id,
            or_(FarmerInventory.available_until.is_(None), FarmerInventory.available_until >= today),
            ~_blocked(viewer_id, FarmerInventory.created_by),
        )
    )
    if req.crop_ids:
        stmt = stmt.where(FarmerInventory.crop.in_(req.crop_ids))
    if req.unit:
        stmt = stmt.where(FarmerInventory.unit == req.unit.lower())
    if req.quantity:
        stmt = stmt.where(or_(FarmerInventory.min_order_qty.is_(None), FarmerInventory.min_order_qty <= req.quantity))
        if not req.allow_partial:
            stmt = stmt.where(FarmerInventory.weight_kg >= req.quantity)
    if req.quality_grades:
        stmt = stmt.where(FarmerInventory.quality_grade.in_([g.upper() for g in req.quality_grades]))
    if req.available_by:
        stmt = stmt.where(or_(FarmerInventory.availability_date.is_(None), FarmerInventory.availability_date <= req.available_by),
                          or_(FarmerInventory.harvest_date.is_(None), FarmerInventory.harvest_date <= req.available_by))
    if req.delivery_option:
        stmt = stmt.where(FarmerInventory.delivery_options.contains(req.delivery_option))
    if req.organic_verified_only:
        stmt = stmt.where(FarmerInventory.organic_verified.is_(True))
    if req.verified_farmers_only:
        stmt = stmt.where(Users.verification_status == VERIFIED)
    if has_origin:
        radius = min(req.radius_km or cfg.default_radius_km, cfg.max_radius_km)
        stmt = stmt.where(lat.isnot(None), lon.isnot(None),
                          geo.within_km(geo.point(lat, lon), geo.origin(req.origin_lat, req.origin_lon), radius))
        stmt = stmt.order_by(distance)
    stmt = stmt.order_by(FarmerInventory.created_at.desc().nullslast(), FarmerInventory.id.desc()).limit(cfg.candidate_limit)

    rows = (await db.execute(stmt)).all()
    completed = await completed_counts(db, list({r[0].created_by for r in rows}))
    return [
        Candidate(
            listing_id=listing.id, farmer_id=listing.created_by, crop_id=listing.crop, crop_name=crop_name or "",
            unit=listing.unit, asking_price=D(listing.proposed_cost), available_qty=D(listing.weight_kg),
            min_order_qty=D(listing.min_order_qty) if listing.min_order_qty else None,
            quality_grade=listing.quality_grade, variety=listing.variety,
            distance_km=round(float(dist), 2) if dist is not None else None,
            farmer_verified=verification == VERIFIED,
            farmer_rating=round(float(avg), 2) if avg is not None else None, farmer_review_count=count or 0,
            completed_orders=completed.get(listing.created_by, 0), harvest_date=listing.harvest_date,
            availability_date=listing.availability_date, organic_verified=bool(listing.organic_verified),
            delivery_options=[o for o in (listing.delivery_options or "").split(",") if o], district=district,
        )
        for listing, crop_name, district, verification, avg, count, dist in rows
    ]


async def _lexical(db: AsyncSession, ids: list[int], query: str | None) -> dict[int, float]:
    if not ids or not query:
        return {}
    rows = (await db.execute(text(
        "SELECT le.listing_id, ts_rank_cd(to_tsvector('simple', le.search_text), to_tsquery('simple', :q)) "
        "FROM listing_embeddings le WHERE le.model_version = :mv AND le.listing_id = ANY(:ids) "
        "AND to_tsvector('simple', le.search_text) @@ to_tsquery('simple', :q)"
    ), {"q": query, "mv": get_embedder().model_version, "ids": ids})).all()
    return {listing_id: float(score) for listing_id, score in rows}


async def _semantic(db: AsyncSession, ids: list[int], query_text: str) -> dict[int, float]:
    if not ids or not query_text.strip():
        return {}
    [vector] = await embed_queries([query_text])
    rows = (await db.execute(text(
        "SELECT listing_id, 1 - (embedding <=> CAST(CAST(:qv AS TEXT) AS vector)) FROM listing_embeddings "
        "WHERE model_version = :mv AND listing_id = ANY(:ids)"
    ), {"qv": vector_literal(vector), "mv": get_embedder().model_version, "ids": ids})).all()
    return {listing_id: float(sim) for listing_id, sim in rows}


async def _revalidate(db: AsyncSession, candidates: list[Candidate], req: SearchRequest) -> list[Candidate]:
    """Stock may have moved while we ranked: re-read the rows and drop anything no longer sellable."""
    if not candidates:
        return []
    live = {
        row.id: row for row in (await db.execute(
            select(FarmerInventory.id, FarmerInventory.status, FarmerInventory.weight_kg, FarmerInventory.proposed_cost,
                   FarmerInventory.available_until, FarmerInventory.deleted_at)
            .where(FarmerInventory.id.in_([c.listing_id for c in candidates]))
        )).all()
    }
    kept = []
    for c in candidates:
        row = live.get(c.listing_id)
        if not row or row.status != ACTIVE or row.deleted_at or D(row.weight_kg) <= 0:
            continue
        if row.available_until and row.available_until < date.today():
            continue
        if req.quantity and not req.allow_partial and D(row.weight_kg) < req.quantity:
            continue
        c.available_qty, c.asking_price = D(row.weight_kg), D(row.proposed_cost)
        kept.append(c)
    return kept


async def hybrid_search(db: AsyncSession, viewer_id: int, req: SearchRequest) -> dict:
    cfg = settings()
    started = time.perf_counter()
    candidates = await _hard_filtered(db, viewer_id, req)
    ids = [c.listing_id for c in candidates]
    timings = {"filter_ms": int((time.perf_counter() - started) * 1000)}

    semantic_used = lexical_used = reranked = False
    indexed_now = 0
    query_text = (req.query_text or "").strip()
    if ids and query_text:
        indexed_now = await index_listings(db, ids[: cfg.embed_on_demand_limit])
        t = time.perf_counter()
        lexical = await _lexical(db, ids, lexical_query(query_text))
        semantic = await _semantic(db, ids, query_text)
        timings["retrieval_ms"] = int((time.perf_counter() - t) * 1000)
        lexical_used, semantic_used = bool(lexical), bool(semantic)
        lexical_rank = sorted(lexical, key=lambda i: -lexical[i])
        semantic_rank = sorted(semantic, key=lambda i: -semantic[i])
        fused = normalise(rrf([r for r in (lexical_rank, semantic_rank) if r], k=cfg.rrf_k))
        for c in candidates:
            c.lexical_score = round(lexical.get(c.listing_id, 0.0), 4)
            c.semantic_score = round(semantic[c.listing_id], 4) if c.listing_id in semantic else None
            c.relevance = fused.get(c.listing_id, 0.0)
        if cfg.reranker_enabled and len(candidates) > 1:
            from src.agents.retrieval.indexer import listing_texts
            from src.agents.retrieval.rerank import rerank_scores

            top = sorted(candidates, key=lambda c: -c.relevance)[: cfg.reranker_top_n]
            texts = await listing_texts(db, [c.listing_id for c in top])
            scores = await rerank_scores(query_text, [texts.get(c.listing_id, "") for c in top])
            ordered = sorted(zip(top, scores), key=lambda pair: -pair[1])
            for position, (c, s) in enumerate(ordered):
                c.rerank_score = round(s, 4)
                c.relevance = 1 - position / max(1, len(ordered))
            reranked = True
    else:
        for c in candidates:
            c.relevance = 1.0  # structured search only: business criteria decide

    ranked = rank(candidates, RankingRequest(quantity=req.quantity, max_price=req.max_price,
                                             target_price=req.target_price, radius_km=req.radius_km),
                  cfg.ranking_weights)
    top = await _revalidate(db, ranked[: (req.limit or cfg.top_k)], req)
    timings["total_ms"] = int((time.perf_counter() - started) * 1000)
    return {
        "matches": [_match_view(c) for c in top],
        "stats": {
            "candidates_after_filters": len(candidates), "returned": len(top), "lexical_used": lexical_used,
            "semantic_used": semantic_used, "reranked": reranked, "indexed_on_demand": indexed_now,
            "embedding_model": get_embedder().model_version if query_text else None, **timings,
        },
    }


def _match_view(c: Candidate) -> dict:
    return {
        "listing_id": c.listing_id, "farmer_id": c.farmer_id, "crop_id": c.crop_id, "crop_name": c.crop_name,
        "variety": c.variety, "asking_price": str(c.asking_price), "unit": c.unit,
        "available_quantity": str(c.available_qty), "min_order_qty": str(c.min_order_qty) if c.min_order_qty else None,
        "quality_grade": c.quality_grade, "distance_km": c.distance_km, "district": c.district,
        "delivery_options": c.delivery_options, "farmer_verified": c.farmer_verified,
        "score": c.score, "score_components": c.components, "reasons": c.reasons,
        "lexical_score": c.lexical_score, "semantic_score": c.semantic_score, "rerank_score": c.rerank_score,
        "price_label": "asking price (final price is negotiated)",
    }


# ---- nearby suppliers and vendor demand --------------------------------------------------------

async def nearby_suppliers(db: AsyncSession, viewer_id: int, lat: float, lon: float, radius_km: float,
                           crop_ids: list[int] | None = None, limit: int = 20) -> list[dict]:
    """Farmers with live listings within the radius (PostGIS on the farm location), nearest first."""
    point = geo.point(FarmerProfiles.latitude, FarmerProfiles.longitude)
    origin = geo.origin(lat, lon)
    radius_km = min(radius_km, settings().max_radius_km)
    live = and_(FarmerInventory.status == ACTIVE, FarmerInventory.deleted_at.is_(None), FarmerInventory.weight_kg > 0)
    if crop_ids:
        live = and_(live, FarmerInventory.crop.in_(crop_ids))
    stmt = (
        select(Users.id, Users.first_name, Users.last_name, Users.verification_status, Districts.district_name,
               geo.distance_km(point, origin).label("distance_km"), func.count(FarmerInventory.id).label("listings"))
        .join(FarmerProfiles, FarmerProfiles.user_id == Users.id)
        .join(FarmerInventory, and_(FarmerInventory.created_by == Users.id, live))
        .outerjoin(Districts, Users.district == Districts.id)
        .where(FarmerProfiles.latitude.isnot(None), FarmerProfiles.longitude.isnot(None),
               geo.within_km(point, origin, radius_km), Users.deleted_at.is_(None), Users.id != viewer_id,
               ~_blocked(viewer_id, Users.id))
        .group_by(Users.id, Districts.district_name, FarmerProfiles.latitude, FarmerProfiles.longitude)
        .order_by("distance_km").limit(limit)
    )
    return [
        {"farmer_id": uid, "name": f"{first or ''} {last or ''}".strip(), "verified": status == VERIFIED,
         "district": district, "distance_km": round(float(distance), 2), "matching_live_listings": listings}
        for uid, first, last, status, district, distance, listings in (await db.execute(stmt)).all()
    ]


async def vendor_demand(db: AsyncSession, farmer_id: int, crop_ids: list[int], *, asking_price: Decimal | None,
                        quantity: Decimal | None, lat: float | None, lon: float | None, radius_km: float | None,
                        limit: int = 20) -> list[dict]:
    """Open buy requests (and active crop alerts) from vendors that match a farmer's produce."""
    if not crop_ids:
        return []
    has_origin = geo.valid_coordinates(lat, lon)
    point = geo.point(VendorProfiles.latitude, VendorProfiles.longitude)
    distance = geo.distance_km(point, geo.origin(lat, lon)).label("distance_km") if has_origin else None
    today = date.today()
    stmt = (
        select(BuyRequests, Crops.crop_name, Users.first_name, Users.last_name, VendorProfiles.business_name,
               *([distance] if distance is not None else []))
        .join(Users, BuyRequests.vendor == Users.id)
        .join(Crops, BuyRequests.crop == Crops.id)
        .outerjoin(VendorProfiles, VendorProfiles.user_id == BuyRequests.vendor)
        .where(BuyRequests.status == "open", BuyRequests.crop.in_(crop_ids), Users.deleted_at.is_(None),
               BuyRequests.vendor != farmer_id, or_(BuyRequests.needed_by.is_(None), BuyRequests.needed_by >= today),
               ~_blocked(farmer_id, BuyRequests.vendor))
        .order_by(BuyRequests.created_at.desc()).limit(200)
    )
    if has_origin and radius_km:
        stmt = stmt.where(or_(VendorProfiles.latitude.is_(None),
                              geo.within_km(point, geo.origin(lat, lon), min(radius_km, settings().max_radius_km))))
    matches = []
    for row in (await db.execute(stmt)).all():
        request, crop_name, first, last, business = row[:5]
        dist = float(row[5]) if has_origin and row[5] is not None else None
        reasons = [f"wants {request.quantity_kg} {request.unit} of {crop_name}"
                   + (f" by {request.needed_by}" if request.needed_by else "")]
        price_ok = True
        if request.max_price_per_kg is not None:
            reasons.append(f"budget up to ₹{request.max_price_per_kg}/{request.unit}")
            if asking_price is not None:
                price_ok = D(request.max_price_per_kg) >= asking_price
                reasons.append("your asking price fits the budget" if price_ok else "your asking price is above the budget")
        if quantity is not None:
            reasons.append("you can fill it fully" if quantity >= D(request.quantity_kg)
                           else f"you can fill {quantity} of {request.quantity_kg} {request.unit}")
        if dist is not None:
            reasons.append(f"{dist:.1f} km away (straight-line)")
        if request.quality_grade:
            reasons.append(f"needs grade {request.quality_grade}")
        score = (0.5 if price_ok else 0.1) + (0.3 * max(0.0, 1 - dist / (radius_km or 100)) if dist is not None else 0.1)
        if quantity is not None and D(request.quantity_kg) > 0:
            score += 0.2 * min(1.0, float(quantity / D(request.quantity_kg)))
        matches.append({
            "type": "buy_request", "buy_request_id": request.id, "vendor_id": request.vendor,
            "vendor_name": business or f"{first or ''} {last or ''}".strip(), "crop_name": crop_name,
            "quantity": request.quantity_kg, "unit": request.unit, "max_price": request.max_price_per_kg,
            "needed_by": request.needed_by, "distance_km": round(dist, 2) if dist is not None else None,
            "score": round(score, 4), "reasons": reasons,
        })
    alerts = (await db.execute(
        select(CropAlerts, Crops.crop_name).join(Crops, CropAlerts.crop == Crops.id)
        .where(CropAlerts.crop.in_(crop_ids), CropAlerts.is_active.is_(True), CropAlerts.vendor != farmer_id,
               ~_blocked(farmer_id, CropAlerts.vendor)).limit(50)
    )).all()
    seen_vendors = {m["vendor_id"] for m in matches}
    for alert, crop_name in alerts:
        if alert.vendor in seen_vendors:
            continue
        seen_vendors.add(alert.vendor)
        reasons = [f"follows new {crop_name} listings"]
        if alert.max_price_per_kg is not None:
            reasons.append(f"alert budget up to ₹{alert.max_price_per_kg}")
        matches.append({"type": "crop_alert", "vendor_id": alert.vendor, "crop_name": crop_name,
                        "max_price": alert.max_price_per_kg, "score": 0.2, "reasons": reasons})
    return sorted(matches, key=lambda m: -m["score"])[:limit]
