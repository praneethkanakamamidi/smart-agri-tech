from datetime import date

from sqlalchemy import select, func, or_, case
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.money import D
from src.data_models.crops_model import Crops
from src.data_models.farmer_inventory_model import FarmerInventory, ACTIVE
from src.data_models.reviews_model import Reviews
from src.data_models.users_model import Users, VERIFIED
from src.services.listing_views import listing_dict, images_for
from src.services.trust_service import completed_counts


class MarketService:
    """Vendor-facing search over live listings. Never exposes private listing fields."""

    async def get_market(self, db: AsyncSession, filters=None, viewer_id: int | None = None) -> list:
        today = date.today()
        rating_sq = (
            select(Reviews.reviewee.label("user_id"), func.avg(Reviews.rating).label("avg_rating"),
                   func.count(Reviews.id).label("review_count"))
            .where(Reviews.is_hidden.is_(False))
            .group_by(Reviews.reviewee)
            .subquery()
        )
        stmt = (
            select(FarmerInventory, rating_sq.c.avg_rating, rating_sq.c.review_count)
            .join(Users, FarmerInventory.created_by == Users.id)
            .join(Crops, FarmerInventory.crop == Crops.id)
            .outerjoin(rating_sq, rating_sq.c.user_id == FarmerInventory.created_by)
            .where(
                FarmerInventory.status == ACTIVE,
                FarmerInventory.deleted_at.is_(None),
                FarmerInventory.weight_kg > 0,
                Users.deleted_at.is_(None),
                or_(FarmerInventory.available_until.is_(None), FarmerInventory.available_until >= today),
            )
            .options(
                joinedload(FarmerInventory.crop_rel),
                joinedload(FarmerInventory.created_by_user).options(
                    joinedload(Users.state_rel), joinedload(Users.district_rel),
                ),
            )
        )

        f = filters
        if f:
            text = f.q or f.search
            if text:
                like = f"%{text.strip()}%"
                stmt = stmt.where(or_(
                    Crops.crop_name.ilike(like), Crops.name_te.ilike(like),
                    FarmerInventory.variety.ilike(like), FarmerInventory.description.ilike(like),
                ))
            if f.crop_id:
                stmt = stmt.where(FarmerInventory.crop == f.crop_id)
            if f.category_id:
                stmt = stmt.where(Crops.category_id == f.category_id)
            if f.variety:
                stmt = stmt.where(FarmerInventory.variety.ilike(f"%{f.variety}%"))
            if f.state_id:
                stmt = stmt.where(Users.state == f.state_id)
            if f.district_id:
                stmt = stmt.where(Users.district == f.district_id)
            if f.farmer_id:
                stmt = stmt.where(FarmerInventory.created_by == f.farmer_id)
            if f.min_price is not None:
                stmt = stmt.where(FarmerInventory.proposed_cost >= f.min_price)
            if f.max_price is not None:
                stmt = stmt.where(FarmerInventory.proposed_cost <= f.max_price)
            if f.min_quantity is not None:
                stmt = stmt.where(FarmerInventory.weight_kg >= f.min_quantity)
            if f.order_quantity is not None:
                stmt = stmt.where(or_(FarmerInventory.min_order_qty.is_(None),
                                      FarmerInventory.min_order_qty <= f.order_quantity))
            if f.unit:
                stmt = stmt.where(FarmerInventory.unit == f.unit.lower())
            if f.quality_grade:
                stmt = stmt.where(FarmerInventory.quality_grade == f.quality_grade)
            if f.harvested_after:
                stmt = stmt.where(FarmerInventory.harvest_date >= f.harvested_after)
            if f.available_by:
                stmt = stmt.where(or_(FarmerInventory.availability_date.is_(None),
                                      FarmerInventory.availability_date <= f.available_by))
            if f.pre_harvest is True:
                stmt = stmt.where(FarmerInventory.harvest_date > today)
            elif f.pre_harvest is False:
                stmt = stmt.where(or_(FarmerInventory.harvest_date.is_(None), FarmerInventory.harvest_date <= today))
            if f.verified_farmers_only:
                stmt = stmt.where(Users.verification_status == VERIFIED)
            if f.organic_verified_only:
                stmt = stmt.where(FarmerInventory.organic_verified.is_(True))
            if f.delivery_option:
                stmt = stmt.where(FarmerInventory.delivery_options.contains(f.delivery_option))

            sort_by = f.sort_by
            if sort_by == "best_match" and f.order_quantity:
                # Listings that can fill the order come first, closest quantity first.
                fills = case((FarmerInventory.weight_kg >= f.order_quantity, 0), else_=1)
                stmt = stmt.order_by(fills, func.abs(FarmerInventory.weight_kg - f.order_quantity),
                                     FarmerInventory.proposed_cost)
            else:
                order = {
                    "newest": FarmerInventory.created_at.desc().nullslast(),
                    "price_asc": FarmerInventory.proposed_cost.asc(),
                    "price_desc": FarmerInventory.proposed_cost.desc(),
                    "quantity_desc": FarmerInventory.weight_kg.desc(),
                    "harvest_desc": FarmerInventory.harvest_date.desc().nullslast(),
                    "harvest_asc": FarmerInventory.harvest_date.asc().nullslast(),
                    "rating_desc": rating_sq.c.avg_rating.desc().nullslast(),
                    "best_match": FarmerInventory.created_at.desc().nullslast(),
                }[sort_by]
                stmt = stmt.order_by(order)
            stmt = stmt.order_by(FarmerInventory.id.desc())
            if f.page_size:
                stmt = stmt.limit(f.page_size).offset((f.page - 1) * f.page_size)
        else:
            stmt = stmt.order_by(FarmerInventory.created_at.desc().nullslast(), FarmerInventory.id.desc())

        rows = (await db.execute(stmt)).unique().all()
        listings = [row[0] for row in rows]
        images = await images_for(db, [l.id for l in listings])
        completed = await completed_counts(db, [l.created_by for l in listings])

        response = []
        for listing, avg_rating, review_count in rows:
            user = listing.created_by_user
            response.append(listing_dict(
                listing, viewer_id,
                farmer_name=f"{user.first_name} {user.last_name}".strip() if user else None,
                farmer_verified=bool(user and user.verification_status == VERIFIED),
                farmer_completed_orders=completed.get(listing.created_by, 0),
                state=user.state_rel.state_name if user and user.state_rel else None,
                district=user.district_rel.district_name if user and user.district_rel else None,
                crop_name=listing.crop_rel.crop_name if listing.crop_rel else None,
                crop_name_te=listing.crop_rel.name_te if listing.crop_rel else None,
                farmer_rating=round(float(avg_rating), 2) if avg_rating is not None else None,
                farmer_review_count=review_count or 0,
                images=images.get(listing.id, [])[:1],
                order_subtotal_at_asking=(
                    D(listing.proposed_cost) * D(f.order_quantity) if f and f.order_quantity else None
                ),
            ))
        return response
