"""
Price intelligence from the platform's own data.

Asking prices (live listings) and negotiated prices (agreed orders) are always reported
separately, with sample size and time range. Statistics below `min_sample_size` are flagged
as not reliable. Reference prices are guidance only - they never restrict a negotiation.
"""
from datetime import timedelta, date

from fastapi import HTTPException
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.money import D
from src.core.platform_settings import get_setting
from src.data_models.buy_requests_model import BuyRequests
from src.data_models.crop_alerts_model import CropAlerts
from src.data_models.crops_model import Crops
from src.data_models.farmer_inventory_model import FarmerInventory, ACTIVE
from src.data_models.miscellaneous_model import Miscellaneous_Data
from src.data_models.orders_model import Orders, DEAL_STATUSES
from src.data_models.users_model import Users
from src.services.notifications_service import notify_user
from src.core.clock import utcnow

DATA_SOURCE = "Smart-Agri-Tech platform records (not an external market feed)"


def _r(value):
    return round(float(value), 2) if value is not None else None


def deal_price():
    return func.coalesce(Orders.unit_price, Orders.total_price / func.nullif(Orders.quantity_kg, 0))


class InsightsService:
    def _deal_stmt(self, columns, crop_id, since, until=None, state_id=None, district_id=None, variety=None,
                   grade=None, unit=None, vendor_id=None):
        stmt = (
            select(*columns)
            .select_from(Orders)
            .join(FarmerInventory, Orders.farmer_inventory == FarmerInventory.id)
            .join(Users, Orders.farmer == Users.id)
            .join(Miscellaneous_Data, Orders.status == Miscellaneous_Data.id)
            .where(Miscellaneous_Data.value.in_(DEAL_STATUSES), Orders.created_at >= since)
        )
        if crop_id:
            stmt = stmt.where(FarmerInventory.crop == crop_id)
        if until:
            stmt = stmt.where(Orders.created_at < until)
        if state_id:
            stmt = stmt.where(Users.state == state_id)
        if district_id:
            stmt = stmt.where(Users.district == district_id)
        if variety:
            stmt = stmt.where(FarmerInventory.variety.ilike(variety))
        if grade:
            stmt = stmt.where(FarmerInventory.quality_grade == grade.upper())
        if unit:
            stmt = stmt.where(Orders.unit == unit)
        if vendor_id:
            stmt = stmt.where(Orders.vendor == vendor_id)
        return stmt

    async def _deal_stats(self, db, crop_id, since, **filters) -> dict:
        price = deal_price()
        row = (await db.execute(self._deal_stmt((
            func.count(Orders.id), func.sum(Orders.quantity_kg),
            func.sum(price * Orders.quantity_kg) / func.nullif(func.sum(Orders.quantity_kg), 0),
            func.percentile_cont(0.5).within_group(price),
            func.min(price), func.max(price),
            func.percentile_cont(0.25).within_group(price), func.percentile_cont(0.75).within_group(price),
        ), crop_id, since, **filters))).one()
        count, volume, avg, median, low, high, p25, p75 = row
        return {"sample_size": count, "volume": _r(volume) or 0, "average": _r(avg), "median": _r(median),
                "min": _r(low), "max": _r(high), "p25": _r(p25), "p75": _r(p75)}

    async def _asking_stats(self, db, crop_id, state_id=None, district_id=None, variety=None, grade=None, unit=None) -> dict:
        stmt = (
            select(func.count(FarmerInventory.id), func.sum(FarmerInventory.weight_kg),
                   func.avg(FarmerInventory.proposed_cost),
                   func.percentile_cont(0.5).within_group(FarmerInventory.proposed_cost),
                   func.min(FarmerInventory.proposed_cost), func.max(FarmerInventory.proposed_cost))
            .join(Users, FarmerInventory.created_by == Users.id)
            .where(FarmerInventory.crop == crop_id, FarmerInventory.status == ACTIVE, FarmerInventory.weight_kg > 0,
                   FarmerInventory.deleted_at.is_(None),
                   or_(FarmerInventory.available_until.is_(None), FarmerInventory.available_until >= date.today()))
        )
        if state_id:
            stmt = stmt.where(Users.state == state_id)
        if district_id:
            stmt = stmt.where(Users.district == district_id)
        if variety:
            stmt = stmt.where(FarmerInventory.variety.ilike(variety))
        if grade:
            stmt = stmt.where(FarmerInventory.quality_grade == grade.upper())
        if unit:
            stmt = stmt.where(FarmerInventory.unit == unit)
        count, qty, avg, median, low, high = (await db.execute(stmt)).one()
        return {"sample_size": count, "available_quantity": _r(qty) or 0, "average": _r(avg), "median": _r(median),
                "min": _r(low), "max": _r(high)}

    async def get_price_insights(self, crop_id: int, db: AsyncSession, state_id=None, district_id=None, days: int = 30,
                                 variety=None, grade=None, unit=None):
        crop = (await db.execute(select(Crops).where(Crops.id == crop_id))).scalar_one_or_none()
        if not crop:
            raise HTTPException(status_code=404, detail="Crop not found.")
        min_sample = int(await get_setting(db, "min_sample_size"))
        since = utcnow() - timedelta(days=days)
        filters = dict(state_id=state_id, district_id=district_id, variety=variety, grade=grade, unit=unit)
        deals = await self._deal_stats(db, crop_id, since, **filters)
        asking = await self._asking_stats(db, crop_id, **filters)
        reliable = deals["sample_size"] >= min_sample
        return {
            "crop_id": crop_id, "crop_name": crop.crop_name,
            "filters": {**filters, "period_days": days, "from": since.date(), "to": date.today()},
            "negotiated_prices": {**deals, "is_reliable": reliable,
                                  "label": "Final agreed prices per unit from confirmed orders"},
            "asking_prices": {**asking, "is_reliable": asking["sample_size"] >= min_sample,
                              "label": "Current asking prices on live listings (not final prices)"},
            "suggested_negotiation_range": {"low": deals["p25"], "high": deals["p75"]} if reliable else None,
            "min_sample_size": min_sample,
            "data_source": DATA_SOURCE,
            "note": None if reliable else "Too few completed deals for a reliable benchmark; treat these numbers with caution.",
        }

    async def get_price_trend(self, crop_id: int, db: AsyncSession, state_id=None, district_id=None, weeks: int = 12,
                              grade=None, unit=None):
        since = utcnow() - timedelta(weeks=weeks)
        week = func.date_trunc("week", Orders.created_at).label("week")
        price = deal_price()
        stmt = self._deal_stmt((
            week, func.count(Orders.id), func.sum(Orders.quantity_kg),
            func.sum(price * Orders.quantity_kg) / func.nullif(func.sum(Orders.quantity_kg), 0),
            func.percentile_cont(0.5).within_group(price),
        ), crop_id, since, state_id=state_id, district_id=district_id, grade=grade, unit=unit).group_by(week).order_by(week)
        min_sample = int(await get_setting(db, "min_sample_size"))
        return {
            "crop_id": crop_id, "weeks": weeks, "data_source": DATA_SOURCE,
            "series": [
                {"week_start": row[0].date() if row[0] else None, "deals": row[1], "volume": _r(row[2]),
                 "average_price": _r(row[3]), "median_price": _r(row[4]), "is_reliable": row[1] >= min_sample}
                for row in (await db.execute(stmt)).all()
            ],
        }

    async def listing_price_check(self, farmer: Users, listing_id: int, db: AsyncSession) -> dict:
        """Compare a farmer's asking price with negotiated prices nearby, in the state and overall."""
        listing = (await db.execute(select(FarmerInventory).where(FarmerInventory.id == listing_id))).scalar_one_or_none()
        if not listing or listing.created_by != farmer.id:
            raise HTTPException(status_code=404, detail="Listing not found.")
        since = utcnow() - timedelta(days=60)
        min_sample = int(await get_setting(db, "min_sample_size"))
        scopes = {}
        for scope, kwargs in (("district", {"district_id": farmer.district}), ("state", {"state_id": farmer.state}),
                              ("all_regions", {})):
            if scope != "all_regions" and not next(iter(kwargs.values())):
                continue
            stats = await self._deal_stats(db, listing.crop, since, unit=listing.unit, grade=listing.quality_grade, **kwargs)
            scopes[scope] = stats
        best = next((s for s in ("district", "state", "all_regions") if s in scopes and scopes[s]["sample_size"] >= min_sample), None)
        asking = D(listing.proposed_cost)
        position = None
        if best:
            ref = scopes[best]
            if ref["p25"] is not None and asking < D(str(ref["p25"])):
                position = "below_typical_range"
            elif ref["p75"] is not None and asking > D(str(ref["p75"])):
                position = "above_typical_range"
            else:
                position = "within_typical_range"
        return {
            "listing_id": listing.id, "asking_price": asking, "unit": listing.unit, "quality_grade": listing.quality_grade,
            "reference_scope": best, "position": position, "references": scopes, "period_days": 60,
            "data_source": DATA_SOURCE,
            "note": "Guidance only - you decide your price." if best else
                    "Not enough recent deals for a reliable comparison.",
        }

    async def procurement_trend(self, vendor: Users, db: AsyncSession, crop_id: int | None = None, months: int = 6) -> dict:
        since = utcnow() - timedelta(days=30 * months)
        month = func.date_trunc("month", Orders.created_at).label("month")
        price = deal_price()
        stmt = self._deal_stmt((
            month, Crops.crop_name, func.count(Orders.id), func.sum(Orders.quantity_kg),
            func.sum(price * Orders.quantity_kg) / func.nullif(func.sum(Orders.quantity_kg), 0),
            func.sum(Orders.total_price),
        ), crop_id, since, vendor_id=vendor.id).join(Crops, FarmerInventory.crop == Crops.id) \
            .group_by(month, Crops.crop_name).order_by(month)
        return {
            "months": months,
            "series": [
                {"month": row[0].date() if row[0] else None, "crop_name": row[1], "orders": row[2],
                 "quantity": _r(row[3]), "average_price": _r(row[4]), "spend": _r(row[5])}
                for row in (await db.execute(stmt)).all()
            ],
        }

    async def demand_forecast(self, crop_id: int, db: AsyncSession, weeks_history: int = 12, horizon: int = 4) -> dict:
        """Weighted moving average of weekly agreed volume plus open procurement demand. An estimate, not a promise."""
        since = utcnow() - timedelta(weeks=weeks_history)
        week = func.date_trunc("week", Orders.created_at).label("week")
        rows = (await db.execute(self._deal_stmt((week, func.sum(Orders.quantity_kg)), crop_id, since)
                                 .group_by(week).order_by(week))).all()
        by_week = {row[0].date(): float(row[1] or 0) for row in rows}
        start = (utcnow() - timedelta(weeks=weeks_history)).date()
        start -= timedelta(days=start.weekday())
        history = []
        for i in range(weeks_history):
            wk = start + timedelta(weeks=i)
            history.append({"week_start": wk, "volume": by_week.get(wk, 0.0)})
        recent = [h["volume"] for h in history[-4:]]
        weights = [1, 2, 3, 4][-len(recent):]
        baseline = sum(v * w for v, w in zip(recent, weights)) / sum(weights) if recent else 0.0
        open_demand = (await db.execute(select(func.coalesce(func.sum(BuyRequests.quantity_kg), 0)).where(
            BuyRequests.crop == crop_id, BuyRequests.status == "open",
            or_(BuyRequests.needed_by.is_(None), BuyRequests.needed_by >= date.today()),
        ))).scalar()
        last_week = history[-1]["week_start"] if history else date.today()
        return {
            "crop_id": crop_id,
            "method": "4-week weighted moving average of agreed volume (weights 1-4); open buy requests listed separately",
            "history": history,
            "forecast": [{"week_start": last_week + timedelta(weeks=i + 1), "expected_volume": round(baseline, 2)}
                         for i in range(horizon)],
            "open_procurement_demand": _r(open_demand),
            "data_source": DATA_SOURCE,
            "is_estimate": True,
        }

    @staticmethod
    async def price_change_alerts(db: AsyncSession) -> int:
        """Weekly job: notify interested users when a crop's median deal price moved meaningfully."""
        threshold = D(await get_setting(db, "price_change_alert_percent"))
        min_sample = int(await get_setting(db, "min_sample_size"))
        now = utcnow()
        this_week, last_week = now - timedelta(days=7), now - timedelta(days=14)
        service = InsightsService()
        crops = (await db.execute(select(Crops.id, Crops.crop_name))).all()
        sent = 0
        for crop_id, crop_name in crops:
            current = await service._deal_stats(db, crop_id, this_week)
            previous = await service._deal_stats(db, crop_id, last_week, until=this_week)
            if current["sample_size"] < min_sample or previous["sample_size"] < min_sample or not previous["median"]:
                continue
            change = (D(str(current["median"])) - D(str(previous["median"]))) * 100 / D(str(previous["median"]))
            if abs(change) < threshold:
                continue
            vendors = (await db.execute(select(CropAlerts.vendor).where(
                CropAlerts.crop == crop_id, CropAlerts.is_active.is_(True)
            ).distinct())).scalars().all()
            farmers = (await db.execute(select(FarmerInventory.created_by).where(
                FarmerInventory.crop == crop_id, FarmerInventory.status == ACTIVE
            ).distinct())).scalars().all()
            unit = (await db.execute(select(Orders.unit).join(FarmerInventory, Orders.farmer_inventory == FarmerInventory.id)
                                     .where(FarmerInventory.crop == crop_id).limit(1))).scalar_one_or_none() or "kg"
            for user_id in set(vendors) | set(farmers):
                created = await notify_user(
                    db, user_id, "price_change_alert",
                    {"crop": crop_name, "change": f"{change:+.1f}", "price": current["median"], "unit": unit},
                    ref_type="crop", ref_id=crop_id, category="reminder",
                    dedupe_key=f"price_change:{crop_id}:{now:%G-%V}",
                )
                sent += 1 if created else 0
        await db.commit()
        return sent
