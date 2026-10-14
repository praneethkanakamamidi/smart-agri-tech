from datetime import datetime, date

from fastapi import HTTPException, status
from sqlalchemy import select, func, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import audit
from src.core.money import D
from src.data_models.catalog_model import Units, QualityStandards
from src.data_models.crops_model import Crops
from src.data_models.crop_alerts_model import CropAlerts
from src.data_models.farmer_inventory_model import (
    FarmerInventory, DRAFT, ACTIVE, PAUSED, RESERVED, SOLD, EXPIRED, ARCHIVED, REMOVED,
)
from src.data_models.favourites_model import FavouriteFarmers
from src.data_models.listing_extras_model import (
    ListingImages, ListingPriceTiers, ListingCertifications, SavedListings, InventoryMovements,
)
from src.data_models.negotiation_model import Negotiations
from src.data_models.orders_model import Orders
from src.data_models.users_model import Users
from src.helpers.serializers import model_to_dict
from src.services import inventory_core
from src.services.files_service import FilesService
from src.services.listing_views import listing_dict, images_for, tiers_for, certifications_for
from src.services.notifications_service import notify_user
from src.services.trust_service import trust_indicators

EDITABLE_STATUSES = (DRAFT, ACTIVE, PAUSED, RESERVED, SOLD, EXPIRED)


def _name(user: Users | None) -> str | None:
    return f"{user.first_name} {user.last_name}".strip() if user else None


class ListingsService:
    # ---- validation helpers --------------------------------------------------

    async def _validate_unit(self, db: AsyncSession, unit: str) -> str:
        unit = unit.lower()
        if not (await db.execute(select(Units.id).where(Units.code == unit, Units.is_active.is_(True)))).first():
            raise HTTPException(status_code=422, detail=f"Unknown unit '{unit}'. See GET /api/catalog/units.")
        return unit

    async def _validate_grade(self, db: AsyncSession, grade: str | None) -> str | None:
        if not grade:
            return None
        grade = grade.upper()
        if not (await db.execute(select(QualityStandards.id).where(
            QualityStandards.code == grade, QualityStandards.is_active.is_(True)
        ))).first():
            raise HTTPException(status_code=422, detail=f"Unknown quality grade '{grade}'. See GET /api/catalog/quality-standards.")
        return grade

    @staticmethod
    def _validate_dates(harvest_date, available_until, availability_date):
        if available_until and available_until < date.today():
            raise HTTPException(status_code=422, detail="available_until cannot be in the past.")
        if harvest_date and available_until and available_until < harvest_date:
            raise HTTPException(status_code=422, detail="available_until cannot be before harvest_date.")
        if availability_date and available_until and availability_date > available_until:
            raise HTTPException(status_code=422, detail="availability_date cannot be after available_until.")

    async def _get_owned(self, db: AsyncSession, listing_id: int, farmer_id: int, lock: bool = False) -> FarmerInventory:
        if lock:
            listing = await inventory_core.lock_listing(db, listing_id)
        else:
            listing = (await db.execute(select(FarmerInventory).where(FarmerInventory.id == listing_id))).scalar_one_or_none()
        if not listing or listing.created_by != farmer_id or listing.deleted_at:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found.")
        return listing

    async def _set_tiers(self, db: AsyncSession, listing_id: int, tiers):
        await db.execute(delete(ListingPriceTiers).where(ListingPriceTiers.listing_id == listing_id))
        seen = set()
        for tier in tiers:
            if tier.min_quantity in seen:
                raise HTTPException(status_code=422, detail="Price tiers must have different minimum quantities.")
            seen.add(tier.min_quantity)
            db.add(ListingPriceTiers(listing_id=listing_id, min_quantity=D(tier.min_quantity), price_per_unit=D(tier.price_per_unit)))

    async def _add_images(self, db: AsyncSession, listing_id: int, owner_id: int, file_ids: list[str]):
        file_ids = await FilesService.require_owned(db, file_ids, owner_id, {"listing_image"})
        count = (await db.execute(select(func.count(ListingImages.id)).where(ListingImages.listing_id == listing_id))).scalar() or 0
        if count + len(file_ids) > 10:
            raise HTTPException(status_code=422, detail="A listing can have at most 10 photos.")
        for offset, file_id in enumerate(file_ids):
            db.add(ListingImages(listing_id=listing_id, file_id=file_id, sort_order=count + offset, created_at=datetime.utcnow()))

    # ---- interested-vendor notifications ------------------------------------

    async def notify_interested_vendors(self, db: AsyncSession, listing: FarmerInventory):
        farmer = (await db.execute(select(Users).where(Users.id == listing.created_by))).scalar_one()
        crop = (await db.execute(select(Crops.crop_name).where(Crops.id == listing.crop))).scalar_one_or_none()
        params = {"party": _name(farmer), "crop": crop, "quantity": D(listing.weight_kg), "unit": listing.unit,
                  "price": D(listing.proposed_cost)}
        notified = set()
        followers = (await db.execute(
            select(FavouriteFarmers.vendor).where(FavouriteFarmers.farmer == listing.created_by)
        )).scalars().all()
        for vendor_id in followers:
            notified.add(vendor_id)
            await notify_user(db, vendor_id, "favourite_new_stock", params, ref_type="listing", ref_id=listing.id,
                              dedupe_key=f"listing_published:{listing.id}")
        alerts = (await db.execute(select(CropAlerts).where(
            CropAlerts.crop == listing.crop,
            CropAlerts.is_active.is_(True),
            CropAlerts.vendor != listing.created_by,
            (CropAlerts.state.is_(None)) | (CropAlerts.state == farmer.state),
            (CropAlerts.district.is_(None)) | (CropAlerts.district == farmer.district),
            (CropAlerts.min_quantity_kg.is_(None)) | (CropAlerts.min_quantity_kg <= listing.weight_kg),
            (CropAlerts.max_price_per_kg.is_(None)) | (CropAlerts.max_price_per_kg >= listing.proposed_cost),
        ))).scalars().all()
        for alert in alerts:
            if alert.vendor in notified:
                continue
            notified.add(alert.vendor)
            await notify_user(db, alert.vendor, "crop_alert_match", params, ref_type="listing", ref_id=listing.id,
                              dedupe_key=f"listing_published:{listing.id}")

    async def _notify_price_change(self, db: AsyncSession, listing: FarmerInventory, old_price):
        farmer = (await db.execute(select(Users).where(Users.id == listing.created_by))).scalar_one()
        crop = (await db.execute(select(Crops.crop_name).where(Crops.id == listing.crop))).scalar_one_or_none()
        savers = (await db.execute(select(SavedListings).where(SavedListings.listing_id == listing.id))).scalars().all()
        for saved in savers:
            await notify_user(
                db, saved.user_id, "saved_listing_price_change",
                {"party": _name(farmer), "crop": crop, "price": D(listing.proposed_cost), "old_price": D(old_price),
                 "unit": listing.unit},
                ref_type="listing", ref_id=listing.id,
            )

    # ---- create / update -----------------------------------------------------

    async def create(self, farmer: Users, payload, db: AsyncSession) -> dict:
        crop = (await db.execute(select(Crops).where(Crops.id == payload.crop))).scalar_one_or_none()
        if not crop:
            raise HTTPException(status_code=404, detail="Crop not found.")
        unit = await self._validate_unit(db, payload.unit or crop.default_unit or "kg")
        grade = await self._validate_grade(db, payload.quality_grade)
        self._validate_dates(payload.harvest_date, payload.available_until, payload.availability_date)
        if payload.publish and payload.quantity <= 0:
            raise HTTPException(status_code=422, detail="Quantity must be positive to publish a listing.")

        now = datetime.utcnow()
        listing = FarmerInventory(
            crop=payload.crop, fertilizer=payload.fertilizer, soil=payload.soil,
            variety=payload.variety, weight_kg=D(payload.quantity), unit=unit,
            proposed_cost=D(payload.asking_price),
            min_order_qty=D(payload.min_order_qty) if payload.min_order_qty else None,
            min_acceptable_price=D(payload.min_acceptable_price) if payload.min_acceptable_price else None,
            quality_grade=grade, harvest_date=payload.harvest_date, available_until=payload.available_until,
            availability_date=payload.availability_date, packaging=payload.packaging, description=payload.description,
            batch_code=payload.batch_code, organic_claim=payload.organic_claim, organic_verified=False,
            delivery_options=",".join(dict.fromkeys(payload.delivery_options)) or "pickup",
            low_stock_threshold=D(payload.low_stock_threshold) if payload.low_stock_threshold is not None else None,
            status=ACTIVE if payload.publish else DRAFT,
            reserved_qty=D(0), sold_qty=D(0), views_count=0, inquiries_count=0,
            created_by=farmer.id, created_at=now, updated_at=now,
            pickup_latitude=payload.pickup_latitude, pickup_longitude=payload.pickup_longitude,
        )
        if (payload.pickup_latitude is None) != (payload.pickup_longitude is None):
            raise HTTPException(status_code=422, detail="Send pickup_latitude and pickup_longitude together.")
        db.add(listing)
        await db.flush()
        inventory_core.initial_ledger(db, listing, farmer.id)
        await self._add_images(db, listing.id, farmer.id, payload.image_file_ids)
        await self._set_tiers(db, listing.id, payload.price_tiers)
        if listing.status == ACTIVE:
            await self.notify_interested_vendors(db, listing)
        audit(db, "listing.created", "listing", listing.id, actor_id=farmer.id, actor_role="farmer",
              after={"status": listing.status, "quantity": listing.weight_kg, "asking_price": listing.proposed_cost})
        await db.commit()
        return {"success": "Listing published." if listing.status == ACTIVE else "Draft saved.", "id": listing.id,
                "status": listing.status}

    async def update(self, farmer: Users, listing_id: int, payload, db: AsyncSession) -> dict:
        listing = await self._get_owned(db, listing_id, farmer.id, lock=True)
        if listing.status not in EDITABLE_STATUSES:
            raise HTTPException(status_code=409, detail=f"A {listing.status} listing can't be edited.")
        before = {"asking_price": listing.proposed_cost, "quantity": listing.weight_kg, "status": listing.status}
        fields = payload.model_dump(exclude_unset=True)
        old_price = listing.proposed_cost

        if "quality_grade" in fields:
            listing.quality_grade = await self._validate_grade(db, payload.quality_grade)
        self._validate_dates(
            fields.get("harvest_date", listing.harvest_date),
            fields.get("available_until", listing.available_until),
            fields.get("availability_date", listing.availability_date),
        )
        for field in ("variety", "harvest_date", "available_until", "availability_date", "packaging",
                      "description", "batch_code", "organic_claim", "pickup_latitude", "pickup_longitude"):
            if field in fields:
                setattr(listing, field, fields[field])
        if (listing.pickup_latitude is None) != (listing.pickup_longitude is None):
            raise HTTPException(status_code=422, detail="Send pickup_latitude and pickup_longitude together.")
        if "organic_claim" in fields and not fields["organic_claim"]:
            listing.organic_verified = False
        if "min_order_qty" in fields:
            listing.min_order_qty = D(payload.min_order_qty) if payload.min_order_qty else None
        if payload.clear_min_acceptable_price:
            listing.min_acceptable_price = None
        elif "min_acceptable_price" in fields and payload.min_acceptable_price:
            listing.min_acceptable_price = D(payload.min_acceptable_price)
        if "low_stock_threshold" in fields:
            listing.low_stock_threshold = D(payload.low_stock_threshold) if payload.low_stock_threshold is not None else None
        if payload.delivery_options:
            listing.delivery_options = ",".join(dict.fromkeys(payload.delivery_options))
        if payload.asking_price is not None:
            listing.proposed_cost = D(payload.asking_price)
        if payload.quantity is not None:
            await inventory_core.set_available(db, listing, payload.quantity, farmer.id, "farmer update")
        if listing.status == EXPIRED and (listing.available_until is None or listing.available_until >= date.today()):
            listing.status = ACTIVE
            inventory_core.refresh_status(listing)

        listing.updated_by = farmer.id
        listing.updated_at = datetime.utcnow()
        if payload.asking_price is not None and D(old_price) != D(payload.asking_price):
            await self._notify_price_change(db, listing, old_price)
        audit(db, "listing.updated", "listing", listing.id, actor_id=farmer.id, actor_role="farmer", before=before,
              after={"asking_price": listing.proposed_cost, "quantity": listing.weight_kg, "status": listing.status})
        await db.commit()
        return {"success": "Listing updated.", "id": listing.id, "status": listing.status}

    async def set_stock(self, farmer: Users, listing_id: int, quantity: float, note: str | None, db: AsyncSession) -> dict:
        listing = await self._get_owned(db, listing_id, farmer.id, lock=True)
        await inventory_core.set_available(db, listing, quantity, farmer.id, note or "stock update")
        listing.updated_at = datetime.utcnow()
        await db.commit()
        return {"success": "Stock updated.", "available": listing.weight_kg, "reserved": listing.reserved_qty,
                "sold": listing.sold_qty, "status": listing.status}

    async def change_status(self, farmer: Users, listing_id: int, action: str, db: AsyncSession) -> dict:
        listing = await self._get_owned(db, listing_id, farmer.id, lock=True)
        if action == "publish":
            if listing.status not in (DRAFT, PAUSED):
                raise HTTPException(status_code=409, detail=f"Only draft or paused listings can be published (this one is {listing.status}).")
            if D(listing.weight_kg) <= 0:
                raise HTTPException(status_code=422, detail="Set a quantity before publishing.")
            if listing.available_until and listing.available_until < date.today():
                raise HTTPException(status_code=422, detail="Update available_until before publishing.")
            was_draft = listing.status == DRAFT
            listing.status = ACTIVE
            inventory_core.refresh_status(listing)
            if was_draft:
                await self.notify_interested_vendors(db, listing)
        elif action == "pause":
            if listing.status not in (ACTIVE, RESERVED):
                raise HTTPException(status_code=409, detail="Only active listings can be paused.")
            listing.status = PAUSED
        else:
            raise HTTPException(status_code=422, detail="Unknown action.")
        listing.updated_at = datetime.utcnow()
        audit(db, f"listing.{action}", "listing", listing.id, actor_id=farmer.id, actor_role="farmer")
        await db.commit()
        return {"success": f"Listing {listing.status}.", "status": listing.status}

    async def duplicate(self, farmer: Users, listing_id: int, db: AsyncSession) -> dict:
        source = await self._get_owned(db, listing_id, farmer.id)
        now = datetime.utcnow()
        copy = FarmerInventory(
            crop=source.crop, fertilizer=source.fertilizer, soil=source.soil, variety=source.variety,
            weight_kg=D(0), unit=source.unit, proposed_cost=source.proposed_cost, min_order_qty=source.min_order_qty,
            min_acceptable_price=source.min_acceptable_price, quality_grade=source.quality_grade,
            packaging=source.packaging, description=source.description, organic_claim=source.organic_claim,
            organic_verified=False, delivery_options=source.delivery_options,
            low_stock_threshold=source.low_stock_threshold, status=DRAFT, reserved_qty=D(0), sold_qty=D(0),
            views_count=0, inquiries_count=0, created_by=farmer.id, created_at=now, updated_at=now,
        )
        db.add(copy)
        await db.flush()
        for tier in (await db.execute(select(ListingPriceTiers).where(ListingPriceTiers.listing_id == source.id))).scalars().all():
            db.add(ListingPriceTiers(listing_id=copy.id, min_quantity=tier.min_quantity, price_per_unit=tier.price_per_unit))
        audit(db, "listing.duplicated", "listing", copy.id, actor_id=farmer.id, actor_role="farmer", after={"source": source.id})
        await db.commit()
        return {"success": "Copied as a draft. Set the quantity, harvest dates and photos, then publish.", "id": copy.id}

    async def delete(self, farmer: Users, listing_id: int, db: AsyncSession) -> dict:
        listing = await self._get_owned(db, listing_id, farmer.id, lock=True)
        if D(listing.reserved_qty) > 0:
            raise HTTPException(status_code=409, detail="This listing has stock reserved for active orders. Pause it instead.")
        has_history = (await db.execute(select(Orders.id).where(Orders.farmer_inventory == listing.id))).first() or \
            (await db.execute(select(Negotiations.id).where(Negotiations.listing_id == listing.id))).first()
        now = datetime.utcnow()
        listing.status = ARCHIVED
        listing.deleted_at = now
        listing.updated_at = now
        audit(db, "listing.deleted", "listing", listing.id, actor_id=farmer.id, actor_role="farmer",
              after={"kept_for_history": bool(has_history)})
        await db.commit()
        return {"success": "Listing deleted."}

    # ---- media, tiers, certifications ------------------------------------------

    async def add_images(self, farmer: Users, listing_id: int, file_ids: list[str], db: AsyncSession) -> dict:
        await self._get_owned(db, listing_id, farmer.id)
        await self._add_images(db, listing_id, farmer.id, file_ids)
        await db.commit()
        return {"images": (await images_for(db, [listing_id])).get(listing_id, [])}

    async def remove_image(self, farmer: Users, listing_id: int, image_id: int, db: AsyncSession) -> dict:
        await self._get_owned(db, listing_id, farmer.id)
        result = await db.execute(delete(ListingImages).where(ListingImages.id == image_id, ListingImages.listing_id == listing_id))
        if not result.rowcount:
            raise HTTPException(status_code=404, detail="Image not found.")
        await db.commit()
        return {"success": "Image removed."}

    async def reorder_images(self, farmer: Users, listing_id: int, image_ids: list[int], db: AsyncSession) -> dict:
        await self._get_owned(db, listing_id, farmer.id)
        for position, image_id in enumerate(image_ids):
            await db.execute(update(ListingImages).where(
                ListingImages.id == image_id, ListingImages.listing_id == listing_id
            ).values(sort_order=position))
        await db.commit()
        return {"images": (await images_for(db, [listing_id])).get(listing_id, [])}

    async def set_price_tiers(self, farmer: Users, listing_id: int, tiers, db: AsyncSession) -> dict:
        await self._get_owned(db, listing_id, farmer.id)
        await self._set_tiers(db, listing_id, tiers)
        audit(db, "listing.price_tiers_set", "listing", listing_id, actor_id=farmer.id, actor_role="farmer",
              after={"tiers": [t.model_dump() for t in tiers]})
        await db.commit()
        return {"price_tiers": await tiers_for(db, listing_id)}

    async def add_certification(self, farmer: Users, listing_id: int, payload, db: AsyncSession) -> dict:
        await self._get_owned(db, listing_id, farmer.id)
        await FilesService.require_owned(db, [payload.file_id], farmer.id, {"certification"})
        cert = ListingCertifications(
            listing_id=listing_id, cert_type=payload.cert_type, issuer=payload.issuer, file_id=payload.file_id,
            valid_until=payload.valid_until, status="pending", created_at=datetime.utcnow(),
        )
        db.add(cert)
        await db.commit()
        return {"success": "Certificate submitted. It is shown as verified only after review.", "certification_id": cert.id}

    # ---- reads -----------------------------------------------------------------

    async def detail(self, listing_id: int, viewer: Users, db: AsyncSession) -> dict:
        listing = (await db.execute(select(FarmerInventory).where(FarmerInventory.id == listing_id))).scalar_one_or_none()
        is_owner = listing is not None and listing.created_by == viewer.id
        is_admin = getattr(viewer, "role_name", None) == "admin"
        if not listing or (listing.deleted_at and not (is_owner or is_admin)) or \
                (listing.status in (DRAFT, REMOVED) and not (is_owner or is_admin)):
            raise HTTPException(status_code=404, detail="Listing not found.")
        if not is_owner:
            await db.execute(update(FarmerInventory).where(FarmerInventory.id == listing_id)
                             .values(views_count=FarmerInventory.views_count + 1))
            await db.commit()
        crop = (await db.execute(select(Crops).where(Crops.id == listing.crop))).scalar_one_or_none()
        farmer = (await db.execute(select(Users).where(Users.id == listing.created_by))).scalar_one()
        saved = (await db.execute(select(SavedListings.id).where(
            SavedListings.user_id == viewer.id, SavedListings.listing_id == listing_id
        ))).first()
        return listing_dict(
            listing, viewer.id,
            crop_name=crop.crop_name if crop else None,
            crop_name_te=crop.name_te if crop else None,
            category_id=crop.category_id if crop else None,
            images=(await images_for(db, [listing_id])).get(listing_id, []),
            price_tiers=await tiers_for(db, listing_id),
            certifications=await certifications_for(db, listing_id, include_unverified=is_owner or is_admin),
            farmer={"id": farmer.id, "name": _name(farmer), "state": farmer.state, "district": farmer.district,
                    "trust": await trust_indicators(db, farmer.id)},
            is_saved=bool(saved),
            can_negotiate=(not is_owner and inventory_core.is_listing_live(listing)),
        )

    async def my_listings(self, farmer: Users, db: AsyncSession, status_filter: str | None = None) -> list[dict]:
        stmt = select(FarmerInventory).where(FarmerInventory.created_by == farmer.id, FarmerInventory.deleted_at.is_(None))
        if status_filter:
            stmt = stmt.where(FarmerInventory.status == status_filter)
        listings = (await db.execute(stmt.order_by(FarmerInventory.created_at.desc().nullslast()))).scalars().all()
        ids = [l.id for l in listings]
        crops = dict((await db.execute(select(Crops.id, Crops.crop_name))).all())
        negotiation_counts, order_counts = {}, {}
        if ids:
            negotiation_counts = dict((await db.execute(
                select(Negotiations.listing_id, func.count(Negotiations.id))
                .where(Negotiations.listing_id.in_(ids)).group_by(Negotiations.listing_id)
            )).all())
            order_counts = dict((await db.execute(
                select(Orders.farmer_inventory, func.count(Orders.id))
                .where(Orders.farmer_inventory.in_(ids)).group_by(Orders.farmer_inventory)
            )).all())
        images = await images_for(db, ids)
        return [
            listing_dict(
                l, farmer.id,
                crop_name=crops.get(l.crop),
                images=images.get(l.id, []),
                stats={
                    "views": l.views_count, "inquiries": l.inquiries_count,
                    "negotiations": negotiation_counts.get(l.id, 0), "orders": order_counts.get(l.id, 0),
                    "sold_quantity": l.sold_qty,
                },
            )
            for l in listings
        ]

    async def farmer_listings(self, farmer_id: int, viewer: Users, db: AsyncSession) -> list[dict]:
        if farmer_id == viewer.id:
            return await self.my_listings(viewer, db)
        listings = (await db.execute(
            select(FarmerInventory).where(
                FarmerInventory.created_by == farmer_id, FarmerInventory.status == ACTIVE,
                FarmerInventory.deleted_at.is_(None),
            ).order_by(FarmerInventory.created_at.desc().nullslast())
        )).scalars().all()
        crops = dict((await db.execute(select(Crops.id, Crops.crop_name))).all())
        images = await images_for(db, [l.id for l in listings])
        return [listing_dict(l, viewer.id, crop_name=crops.get(l.crop), images=images.get(l.id, [])) for l in listings]

    async def stock_history(self, farmer: Users, listing_id: int, db: AsyncSession) -> list[dict]:
        await self._get_owned(db, listing_id, farmer.id)
        rows = (await db.execute(
            select(InventoryMovements).where(InventoryMovements.listing_id == listing_id)
            .order_by(InventoryMovements.created_at.desc(), InventoryMovements.id.desc())
        )).scalars().all()
        return [model_to_dict(r) for r in rows]

    # ---- saved listings (vendor wishlist) ----------------------------------------

    async def save(self, user: Users, listing_id: int, db: AsyncSession) -> dict:
        listing = (await db.execute(select(FarmerInventory).where(FarmerInventory.id == listing_id))).scalar_one_or_none()
        if not listing or listing.deleted_at or listing.status in (DRAFT, REMOVED):
            raise HTTPException(status_code=404, detail="Listing not found.")
        if listing.created_by == user.id:
            raise HTTPException(status_code=422, detail="You can't save your own listing.")
        exists = (await db.execute(select(SavedListings.id).where(
            SavedListings.user_id == user.id, SavedListings.listing_id == listing_id
        ))).first()
        if not exists:
            db.add(SavedListings(user_id=user.id, listing_id=listing_id, saved_price=listing.proposed_cost,
                                 created_at=datetime.utcnow()))
            await db.commit()
        return {"success": "Listing saved. You'll be notified if its price changes."}

    async def unsave(self, user: Users, listing_id: int, db: AsyncSession) -> dict:
        await db.execute(delete(SavedListings).where(SavedListings.user_id == user.id, SavedListings.listing_id == listing_id))
        await db.commit()
        return {"success": "Listing removed from saved."}

    async def saved(self, user: Users, db: AsyncSession) -> list[dict]:
        rows = (await db.execute(
            select(SavedListings, FarmerInventory)
            .join(FarmerInventory, SavedListings.listing_id == FarmerInventory.id)
            .where(SavedListings.user_id == user.id)
            .order_by(SavedListings.created_at.desc())
        )).all()
        crops = dict((await db.execute(select(Crops.id, Crops.crop_name))).all())
        return [
            listing_dict(
                listing, user.id, crop_name=crops.get(listing.crop),
                saved_at=saved.created_at, saved_price=saved.saved_price,
                is_available=inventory_core.is_listing_live(listing),
                price_changed_since_saved=(saved.saved_price is not None and D(saved.saved_price) != D(listing.proposed_cost)),
            )
            for saved, listing in rows
        ]
