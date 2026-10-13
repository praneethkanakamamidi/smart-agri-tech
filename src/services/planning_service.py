"""Harvest planning (farmers) and recurring supply agreements (vendor proposes, farmer approves)."""
from datetime import datetime, date, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import audit
from src.core.money import D
from src.data_models.crops_model import Crops
from src.data_models.farmer_inventory_model import FarmerInventory
from src.data_models.listing_extras_model import HarvestPlans
from src.data_models.platform_model import RecurringOrders
from src.data_models.users_model import Users
from src.helpers.serializers import model_to_dict
from src.schemas.listings_schema import ListingCreateSchema
from src.services import inventory_core, order_core
from src.services.listings_service import ListingsService
from src.services.notifications_service import notify_user

FREQUENCY_DAYS = {"weekly": 7, "biweekly": 14, "monthly": 30}


def _name(u):
    return f"{u.first_name} {u.last_name}".strip() if u else ""


class PlanningService:
    # ---- harvest plans -------------------------------------------------------------

    async def create_plan(self, farmer: Users, payload, db: AsyncSession) -> dict:
        if not (await db.execute(select(Crops.id).where(Crops.id == payload.crop))).first():
            raise HTTPException(status_code=404, detail="Crop not found.")
        now = datetime.utcnow()
        plan = HarvestPlans(farmer=farmer.id, status="planned", created_at=now, updated_at=now,
                            **payload.model_dump(exclude={"expected_quantity", "area_acres"}),
                            expected_quantity=D(payload.expected_quantity),
                            area_acres=D(payload.area_acres) if payload.area_acres is not None else None)
        db.add(plan)
        await db.commit()
        return {"success": "Harvest plan saved.", "plan_id": plan.id}

    async def _owned_plan(self, db, plan_id: int, farmer_id: int) -> HarvestPlans:
        plan = (await db.execute(select(HarvestPlans).where(HarvestPlans.id == plan_id))).scalar_one_or_none()
        if not plan or plan.farmer != farmer_id:
            raise HTTPException(status_code=404, detail="Harvest plan not found.")
        return plan

    async def update_plan(self, farmer: Users, plan_id: int, payload, db: AsyncSession) -> dict:
        plan = await self._owned_plan(db, plan_id, farmer.id)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(plan, key, D(value) if key in ("expected_quantity", "area_acres") and value is not None else value)
        plan.updated_at = datetime.utcnow()
        await db.commit()
        return model_to_dict(plan)

    async def calendar(self, farmer: Users, db: AsyncSession, date_from: date | None, date_to: date | None) -> list[dict]:
        date_from = date_from or date.today() - timedelta(days=30)
        date_to = date_to or date.today() + timedelta(days=180)
        rows = (await db.execute(
            select(HarvestPlans, Crops.crop_name).join(Crops, HarvestPlans.crop == Crops.id)
            .where(HarvestPlans.farmer == farmer.id, HarvestPlans.expected_harvest_date.between(date_from, date_to))
            .order_by(HarvestPlans.expected_harvest_date)
        )).all()
        return [model_to_dict(p, crop_name=c, days_to_harvest=(p.expected_harvest_date - date.today()).days) for p, c in rows]

    async def publish_plan(self, farmer: Users, plan_id: int, payload, db: AsyncSession) -> dict:
        """Publish a planned harvest as a pre-harvest listing vendors can book in advance."""
        plan = await self._owned_plan(db, plan_id, farmer.id)
        if plan.listing_id:
            raise HTTPException(status_code=409, detail="This plan is already listed.")
        if plan.status != "planned":
            raise HTTPException(status_code=409, detail=f"This plan is {plan.status}.")
        listing_payload = ListingCreateSchema(
            crop=plan.crop, variety=plan.variety, quantity=float(plan.expected_quantity), unit=plan.unit,
            asking_price=payload.asking_price, min_order_qty=payload.min_order_qty,
            min_acceptable_price=payload.min_acceptable_price, harvest_date=plan.expected_harvest_date,
            availability_date=plan.expected_harvest_date, available_until=payload.available_until,
            description=payload.description or f"Pre-harvest booking. Expected harvest {plan.expected_harvest_date}.",
            delivery_options=payload.delivery_options, publish=True,
        )
        result = await ListingsService().create(farmer, listing_payload, db)
        plan.listing_id = result["id"]
        plan.updated_at = datetime.utcnow()
        await db.commit()
        return {**result, "success": "Published as a pre-harvest listing.", "plan_id": plan.id}

    # ---- recurring supply ------------------------------------------------------------

    async def propose_recurring(self, vendor: Users, payload, db: AsyncSession) -> dict:
        listing = (await db.execute(select(FarmerInventory).where(FarmerInventory.id == payload.listing_id))).scalar_one_or_none()
        if not listing or listing.deleted_at or listing.created_by == vendor.id:
            raise HTTPException(status_code=404, detail="Listing not found.")
        if payload.start_date < date.today():
            raise HTTPException(status_code=422, detail="start_date cannot be in the past.")
        now = datetime.utcnow()
        recurring = RecurringOrders(
            vendor=vendor.id, farmer=listing.created_by, listing_id=listing.id, quantity=D(payload.quantity),
            unit_price=D(payload.unit_price), frequency=payload.frequency, next_run_date=payload.start_date,
            end_date=payload.end_date, fulfillment_mode=payload.fulfillment_mode, payment_terms=payload.payment_terms,
            status="proposed", notes=payload.notes, created_at=now, updated_at=now,
        )
        db.add(recurring)
        await db.flush()
        crop = (await db.execute(select(Crops.crop_name).where(Crops.id == listing.crop))).scalar_one_or_none()
        await notify_user(db, listing.created_by, "recurring_proposed",
                          {"party": _name(vendor), "quantity": D(payload.quantity), "unit": listing.unit, "crop": crop,
                           "frequency": payload.frequency, "price": D(payload.unit_price)},
                          ref_type="recurring_order", ref_id=recurring.id)
        audit(db, "recurring.proposed", "recurring_order", recurring.id, actor_id=vendor.id, actor_role="vendor")
        await db.commit()
        return {"success": "Recurring supply proposed. The farmer must approve it.", "recurring_id": recurring.id}

    async def list_recurring(self, user: Users, db: AsyncSession) -> list[dict]:
        rows = (await db.execute(select(RecurringOrders).where(
            (RecurringOrders.vendor == user.id) | (RecurringOrders.farmer == user.id)
        ).order_by(RecurringOrders.created_at.desc()))).scalars().all()
        return [model_to_dict(r, my_role="vendor" if r.vendor == user.id else "farmer") for r in rows]

    async def change_recurring(self, user: Users, recurring_id: int, action: str, db: AsyncSession) -> dict:
        r = (await db.execute(select(RecurringOrders).where(RecurringOrders.id == recurring_id).with_for_update())).scalar_one_or_none()
        if not r or user.id not in (r.vendor, r.farmer):
            raise HTTPException(status_code=404, detail="Recurring supply not found.")
        is_farmer = user.id == r.farmer
        transitions = {
            ("approve", "proposed"): ("active", is_farmer),
            ("reject", "proposed"): ("rejected", is_farmer),
            ("pause", "active"): ("paused", True),
            ("resume", "paused"): ("active", True),
            ("cancel", "proposed"): ("cancelled", not is_farmer),
            ("cancel", "active"): ("cancelled", True),
            ("cancel", "paused"): ("cancelled", True),
        }
        rule = transitions.get((action, r.status))
        if not rule or not rule[1]:
            raise HTTPException(status_code=409, detail=f"You can't {action} a {r.status} recurring supply.")
        r.status = rule[0]
        r.updated_at = datetime.utcnow()
        if action == "approve":
            r.approved_at = r.updated_at
        other = r.vendor if is_farmer else r.farmer
        await notify_user(db, other, "recurring_update", {"recurring_id": r.id, "status": r.status},
                          ref_type="recurring_order", ref_id=r.id)
        audit(db, f"recurring.{action}", "recurring_order", r.id, actor_id=user.id)
        await db.commit()
        return {"success": f"Recurring supply {r.status}.", "status": r.status}

    @staticmethod
    async def run_due_recurring(db: AsyncSession) -> int:
        """Scheduler: create the next order for each approved recurring supply that is due."""
        due = (await db.execute(select(RecurringOrders).where(
            RecurringOrders.status == "active", RecurringOrders.next_run_date <= date.today(),
        ).with_for_update(skip_locked=True))).scalars().all()
        created = 0
        for r in due:
            if r.end_date and r.next_run_date > r.end_date:
                r.status = "cancelled"
                continue
            try:
                async with db.begin_nested():  # a failed order rolls back only its own savepoint
                    listing = await inventory_core.lock_listing(db, r.listing_id)
                    order = await order_core.create_order(
                        db, listing=listing, vendor_id=r.vendor, quantity=r.quantity, unit_price=r.unit_price,
                        source="recurring", accepted_by=None, fulfillment_mode=r.fulfillment_mode,
                        payment_terms=r.payment_terms, farmer_confirmed=True, vendor_confirmed=True,
                        extra_terms={"recurring_id": r.id},
                    )
                r.last_order_id = order.id
                created += 1
            except HTTPException:
                crop = (await db.execute(select(Crops.crop_name).join(FarmerInventory, FarmerInventory.crop == Crops.id)
                                         .where(FarmerInventory.id == r.listing_id))).scalar_one_or_none()
                for party_id in (r.vendor, r.farmer):
                    await notify_user(db, party_id, "recurring_skipped", {"recurring_id": r.id, "crop": crop},
                                      ref_type="recurring_order", ref_id=r.id,
                                      dedupe_key=f"recurring_skipped:{r.id}:{r.next_run_date}")
            r.next_run_date = r.next_run_date + timedelta(days=FREQUENCY_DAYS[r.frequency])
            r.updated_at = datetime.utcnow()
        await db.commit()
        return created
