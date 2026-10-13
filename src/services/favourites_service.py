from fastapi import HTTPException, status
from sqlalchemy import select, func, or_
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, date

from src.data_models.favourites_model import FavouriteFarmers
from src.data_models.farmer_inventory_model import FarmerInventory
from src.data_models.users_model import Users
from src.data_models.reviews_model import Reviews
from src.security_utils.role_guard import get_role_name, FARMER
from src.data_models.farmer_inventory_model import ACTIVE
from src.services.listing_views import listing_dict


class FavouritesService:
    """Vendors follow trusted farmers and get a feed of their new stock."""

    async def add_favourite(self, farmer_id: int, vendor_id: int, db: AsyncSession):
        try:
            farmer = (await db.execute(select(Users).where(Users.id == farmer_id))).scalar_one_or_none()
            if not farmer or await get_role_name(farmer, db) != FARMER:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farmer not found.")

            existing = await db.execute(
                select(FavouriteFarmers.id).where(
                    FavouriteFarmers.vendor == vendor_id, FavouriteFarmers.farmer == farmer_id
                )
            )
            if existing.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="Farmer is already in your favourites."
                )

            db.add(FavouriteFarmers(vendor=vendor_id, farmer=farmer_id, created_at=datetime.utcnow()))
            await db.commit()
            return {"success": "Farmer added to favourites."}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def remove_favourite(self, farmer_id: int, vendor_id: int, db: AsyncSession):
        try:
            favourite = (
                await db.execute(
                    select(FavouriteFarmers).where(
                        FavouriteFarmers.vendor == vendor_id, FavouriteFarmers.farmer == farmer_id
                    )
                )
            ).scalar_one_or_none()
            if not favourite:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Farmer is not in your favourites."
                )
            await db.delete(favourite)
            await db.commit()
            return {"success": "Farmer removed from favourites."}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def list_favourites(self, vendor_id: int, db: AsyncSession):
        try:
            stmt = (
                select(FavouriteFarmers)
                .where(FavouriteFarmers.vendor == vendor_id)
                .options(joinedload(FavouriteFarmers.farmer_user))
                .order_by(FavouriteFarmers.created_at.desc())
            )
            favourites = (await db.execute(stmt)).scalars().unique().all()
            farmer_ids = [f.farmer for f in favourites]
            if not farmer_ids:
                return []

            listing_counts = dict((await db.execute(
                select(FarmerInventory.created_by, func.count(FarmerInventory.id))
                .where(FarmerInventory.created_by.in_(farmer_ids), FarmerInventory.weight_kg > 0)
                .group_by(FarmerInventory.created_by)
            )).all())
            ratings = {
                row[0]: round(float(row[1]), 2)
                for row in (await db.execute(
                    select(Reviews.reviewee, func.avg(Reviews.rating))
                    .where(Reviews.reviewee.in_(farmer_ids))
                    .group_by(Reviews.reviewee)
                )).all()
            }

            return [
                {
                    "farmer_id": f.farmer,
                    "farmer_name": f"{f.farmer_user.first_name} {f.farmer_user.last_name}" if f.farmer_user else None,
                    "active_listings": listing_counts.get(f.farmer, 0),
                    "average_rating": ratings.get(f.farmer),
                    "followed_at": f.created_at,
                }
                for f in favourites
            ]
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def get_feed(self, vendor_id: int, db: AsyncSession, page: int = 1, page_size: int = 20):
        """Available listings from favourite farmers, newest first."""
        try:
            favourite_farmers = select(FavouriteFarmers.farmer).where(FavouriteFarmers.vendor == vendor_id)
            stmt = (
                select(FarmerInventory)
                .where(
                    FarmerInventory.created_by.in_(favourite_farmers),
                    FarmerInventory.status == ACTIVE,
                    FarmerInventory.deleted_at.is_(None),
                    FarmerInventory.weight_kg > 0,
                    or_(FarmerInventory.available_until.is_(None), FarmerInventory.available_until >= date.today()),
                )
                .options(
                    joinedload(FarmerInventory.crop_rel),
                    joinedload(FarmerInventory.created_by_user),
                )
                .order_by(FarmerInventory.created_at.desc().nullslast(), FarmerInventory.id.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
            listings = (await db.execute(stmt)).scalars().unique().all()
            return [
                listing_dict(
                    item, vendor_id,
                    crop_name=item.crop_rel.crop_name if item.crop_rel else None,
                    farmer_name=(
                        f"{item.created_by_user.first_name} {item.created_by_user.last_name}"
                        if item.created_by_user else None
                    ),
                )
                for item in listings
            ]
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )
