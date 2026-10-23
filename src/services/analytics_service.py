"""
Reports and marketplace metrics with explicit definitions. Pending orders are never mixed
with completed transactions.
"""
from datetime import datetime, timedelta, date

from fastapi import HTTPException
from sqlalchemy import select, func, or_, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.lookups import misc_id
from src.core.money import money, D
from src.data_models.crops_model import Crops
from src.data_models.disputes_model import Disputes
from src.data_models.farmer_inventory_model import FarmerInventory, ACTIVE
from src.data_models.miscellaneous_model import Miscellaneous_Data
from src.data_models.negotiation_model import (
    Negotiations, Offers, ACCEPTED, REJECTED, EXPIRED, CANCELLED as NEG_CANCELLED, COUNTERED,
)
from src.data_models.orders_model import (
    Orders, COMPLETED, DELIVERED, CANCELLED, DEAL_STATUSES,
)
from src.data_models.roles_model import Roles
from src.data_models.transactions_model import Transactions, Refunds, Settlements
from src.data_models.users_model import Users, VERIFIED
from src.services.trust_service import trust_indicators
from src.core.clock import utcnow

PERIODS = {"day": "day", "week": "week", "month": "month"}


def _period_range(date_from: date | None, date_to: date | None, default_days: int = 90):
    end = datetime.combine(date_to, datetime.max.time()) if date_to else utcnow()
    start = datetime.combine(date_from, datetime.min.time()) if date_from else end - timedelta(days=default_days)
    if start > end:
        raise HTTPException(status_code=422, detail="date_from must be before date_to.")
    return start, end


def _pct(numerator, denominator):
    return round(numerator * 100.0 / denominator, 1) if denominator else None


def _f(value):
    return round(float(value), 2) if value is not None else None


def _deal_price():
    return func.coalesce(Orders.unit_price, Orders.total_price / func.nullif(Orders.quantity_kg, 0))


class AnalyticsService:
    async def _series(self, db, party_column, user_id, start, end, period, statuses):
        bucket = func.date_trunc(PERIODS[period], Orders.completed_at if statuses == (COMPLETED,) else Orders.created_at).label("bucket")
        rows = (await db.execute(
            select(bucket, func.count(Orders.id), func.sum(Orders.total_price), func.sum(Orders.quantity_kg))
            .join(Miscellaneous_Data, Orders.status == Miscellaneous_Data.id)
            .where(party_column == user_id, Miscellaneous_Data.value.in_(statuses),
                   Orders.created_at.between(start, end))
            .group_by(bucket).order_by(bucket)
        )).all()
        return [{"period_start": b.date() if b else None, "orders": n, "value": v, "quantity": q} for b, n, v, q in rows]

    async def _by_crop(self, db, party_column, user_id, start, end, statuses):
        price = _deal_price()
        rows = (await db.execute(
            select(Crops.crop_name, Orders.unit, func.count(Orders.id), func.sum(Orders.quantity_kg),
                   func.sum(price * Orders.quantity_kg) / func.nullif(func.sum(Orders.quantity_kg), 0),
                   func.sum(Orders.total_price))
            .join(FarmerInventory, Orders.farmer_inventory == FarmerInventory.id)
            .join(Crops, FarmerInventory.crop == Crops.id)
            .join(Miscellaneous_Data, Orders.status == Miscellaneous_Data.id)
            .where(party_column == user_id, Miscellaneous_Data.value.in_(statuses), Orders.created_at.between(start, end))
            .group_by(Crops.crop_name, Orders.unit).order_by(func.sum(Orders.total_price).desc())
        )).all()
        return [{"crop_name": c, "unit": u, "orders": n, "quantity": q, "average_price": _f(a), "value": v}
                for c, u, n, q, a, v in rows]

    async def farmer_report(self, farmer: Users, db: AsyncSession, period="month", date_from=None, date_to=None) -> dict:
        start, end = _period_range(date_from, date_to)
        listings = (await db.execute(select(FarmerInventory.id).where(
            FarmerInventory.created_by == farmer.id, FarmerInventory.created_at.between(start, end)
        ))).scalars().all()
        sold_listings = (await db.execute(select(func.count(distinct(Orders.farmer_inventory))).where(
            Orders.farmer_inventory.in_(listings))) if listings else None)
        sold_count = sold_listings.scalar() if sold_listings is not None else 0
        offers = dict((await db.execute(
            select(Offers.status, func.count(Offers.id))
            .where(Offers.recipient == farmer.id, Offers.created_at.between(start, end))
            .group_by(Offers.status)
        )).all())
        decided = sum(offers.get(s, 0) for s in (ACCEPTED, REJECTED, COUNTERED, EXPIRED))
        settlements = (await db.execute(select(func.coalesce(func.sum(Settlements.net_amount), 0)).where(
            Settlements.farmer == farmer.id, Settlements.status == "pending"))).scalar()
        vendors = (await db.execute(
            select(Users.id, Users.first_name, Users.last_name, func.count(Orders.id), func.sum(Orders.total_price))
            .join(Users, Orders.vendor == Users.id)
            .join(Miscellaneous_Data, Orders.status == Miscellaneous_Data.id)
            .where(Orders.farmer == farmer.id, Miscellaneous_Data.value.in_(DEAL_STATUSES),
                   Orders.created_at.between(start, end))
            .group_by(Users.id, Users.first_name, Users.last_name).order_by(func.count(Orders.id).desc()).limit(10)
        )).all()
        completed = await self._series(db, Orders.farmer, farmer.id, start, end, period, (COMPLETED,))
        return {
            "from": start, "to": end, "period": period,
            "completed_sales": completed,
            "booked_orders": await self._series(db, Orders.farmer, farmer.id, start, end, period, DEAL_STATUSES),
            "sales_by_crop": await self._by_crop(db, Orders.farmer, farmer.id, start, end, (COMPLETED, DELIVERED)),
            "listing_conversion_rate_percent": _pct(sold_count, len(listings)),
            "offer_acceptance_rate_percent": _pct(offers.get(ACCEPTED, 0), decided),
            "offers_received": sum(offers.values()),
            "pending_settlements": money(settlements),
            "frequent_vendors": [{"vendor_id": i, "name": f"{a} {b}".strip(), "orders": n, "value": v}
                                 for i, a, b, n, v in vendors],
            "definitions": {
                "completed_sales": "Orders that reached COMPLETED, bucketed by completion date.",
                "booked_orders": "Agreed orders (confirmed or later, incl. disputed), by creation date.",
                "listing_conversion_rate_percent": "Listings created in the period that received at least one order.",
                "offer_acceptance_rate_percent": "Offers you received that you accepted, out of those you decided or that expired.",
            },
        }

    async def vendor_report(self, vendor: Users, db: AsyncSession, period="month", date_from=None, date_to=None) -> dict:
        start, end = _period_range(date_from, date_to)
        paid_id = await misc_id(db, "payment_status", "paid")
        bucket = func.date_trunc(PERIODS[period], Transactions.updated_at).label("bucket")
        spend = (await db.execute(
            select(bucket, func.sum(Transactions.amount_paid)).join(Orders, Transactions.order_id == Orders.id)
            .where(Orders.vendor == vendor.id, Transactions.status == paid_id, Transactions.updated_at.between(start, end))
            .group_by(bucket).order_by(bucket)
        )).all()
        price = _deal_price()
        suppliers = (await db.execute(
            select(Users.id, Users.first_name, Users.last_name, func.count(Orders.id),
                   func.sum(price * Orders.quantity_kg) / func.nullif(func.sum(Orders.quantity_kg), 0),
                   func.count(Orders.id).filter(func.date(Orders.delivered_at) <= Orders.expected_delivery_date),
                   func.count(Orders.id).filter(Orders.expected_delivery_date.is_not(None), Orders.delivered_at.is_not(None)))
            .join(Users, Orders.farmer == Users.id)
            .join(Miscellaneous_Data, Orders.status == Miscellaneous_Data.id)
            .where(Orders.vendor == vendor.id, Miscellaneous_Data.value.in_(DEAL_STATUSES),
                   Orders.created_at.between(start, end))
            .group_by(Users.id, Users.first_name, Users.last_name)
        )).all()
        disputes = dict((await db.execute(
            select(Disputes.against, func.count(Disputes.id)).where(Disputes.raised_by == vendor.id).group_by(Disputes.against)
        )).all())
        recurring = (await db.execute(
            select(Orders).where(Orders.vendor == vendor.id, Orders.source == "recurring",
                                 Orders.created_at.between(start, end)).order_by(Orders.created_at.desc())
        )).scalars().all()
        from src.services.dashboard_service import DashboardService
        return {
            "from": start, "to": end, "period": period,
            "procurement_spend": [{"period_start": b.date() if b else None, "spend": v} for b, v in spend],
            "purchases_by_produce": await self._by_crop(db, Orders.vendor, vendor.id, start, end, DEAL_STATUSES),
            "supplier_comparison": [
                {"farmer_id": i, "name": f"{a} {b}".strip(), "orders": n, "average_price": _f(avg),
                 "on_time_percent": _pct(on_time, with_date), "disputes_raised": disputes.get(i, 0)}
                for i, a, b, n, avg, on_time, with_date in suppliers
            ],
            "outstanding_payments": await DashboardService()._outstanding(db, Orders.vendor, vendor.id),
            "recurring_purchases": [
                {"order_id": o.id, "order_number": o.order_number, "total": o.total_price, "created_at": o.created_at}
                for o in recurring
            ],
        }

    async def compare_suppliers(self, vendor: Users, db: AsyncSession, farmer_ids: list[int], crop_id: int | None) -> list[dict]:
        if not farmer_ids or len(farmer_ids) > 10:
            raise HTTPException(status_code=422, detail="Compare between 1 and 10 farmers.")
        price = _deal_price()
        result = []
        for farmer_id in farmer_ids:
            farmer = (await db.execute(select(Users).where(Users.id == farmer_id))).scalar_one_or_none()
            if not farmer:
                continue
            listing_stmt = select(FarmerInventory).where(
                FarmerInventory.created_by == farmer_id, FarmerInventory.status == ACTIVE,
                FarmerInventory.deleted_at.is_(None))
            if crop_id:
                listing_stmt = listing_stmt.where(FarmerInventory.crop == crop_id)
            listings = (await db.execute(listing_stmt)).scalars().all()
            deal_stmt = (
                select(func.count(Orders.id),
                       func.sum(price * Orders.quantity_kg) / func.nullif(func.sum(Orders.quantity_kg), 0))
                .join(FarmerInventory, Orders.farmer_inventory == FarmerInventory.id)
                .join(Miscellaneous_Data, Orders.status == Miscellaneous_Data.id)
                .where(Orders.farmer == farmer_id, Miscellaneous_Data.value.in_(DEAL_STATUSES))
            )
            if crop_id:
                deal_stmt = deal_stmt.where(FarmerInventory.crop == crop_id)
            all_deals = (await db.execute(deal_stmt)).one()
            with_me = (await db.execute(deal_stmt.where(Orders.vendor == vendor.id))).one()
            result.append({
                "farmer_id": farmer_id,
                "name": f"{farmer.first_name} {farmer.last_name}".strip(),
                "trust": await trust_indicators(db, farmer_id),
                "live_listings": [
                    {"listing_id": l.id, "asking_price": l.proposed_cost, "unit": l.unit, "available": l.weight_kg,
                     "quality_grade": l.quality_grade, "min_order_qty": l.min_order_qty} for l in listings
                ],
                "deals_overall": {"count": all_deals[0], "average_price": _f(all_deals[1])},
                "deals_with_me": {"count": with_me[0], "average_price": _f(with_me[1])},
            })
        return result

    async def admin_report(self, db: AsyncSession, date_from=None, date_to=None) -> dict:
        start, end = _period_range(date_from, date_to, 30)
        role_counts = dict((await db.execute(
            select(func.lower(Roles.name), func.count(Users.id)).join(Roles, Users.role_id == Roles.id)
            .where(Users.deleted_at.is_(None)).group_by(func.lower(Roles.name))
        )).all())
        verified = dict((await db.execute(
            select(func.lower(Roles.name), func.count(Users.id)).join(Roles, Users.role_id == Roles.id)
            .where(Users.verification_status == VERIFIED).group_by(func.lower(Roles.name))
        )).all())
        new_users = (await db.execute(select(func.count(Users.id)).where(Users.created_time.between(start, end)))).scalar()
        status_counts = dict((await db.execute(
            select(Miscellaneous_Data.value, func.count(Orders.id), )
            .join(Miscellaneous_Data, Orders.status == Miscellaneous_Data.id)
            .where(Orders.created_at.between(start, end)).group_by(Miscellaneous_Data.value)
        )).all())
        completed_value = (await db.execute(
            select(func.coalesce(func.sum(Orders.total_price), 0), func.coalesce(func.sum(Orders.platform_fee + Orders.tax_amount), 0))
            .join(Miscellaneous_Data, Orders.status == Miscellaneous_Data.id)
            .where(Miscellaneous_Data.value == COMPLETED, Orders.completed_at.between(start, end))
        )).one()
        total_orders = sum(status_counts.values())
        paid_id, failed_id = await misc_id(db, "payment_status", "paid"), await misc_id(db, "payment_status", "failed")
        payments = dict((await db.execute(
            select(Transactions.status, func.count(Transactions.id))
            .where(Transactions.created_at.between(start, end), Transactions.status.in_((paid_id, failed_id)))
            .group_by(Transactions.status)
        )).all())
        disputes = (await db.execute(select(func.count(Disputes.id)).where(Disputes.created_at.between(start, end)))).scalar()
        refunds = (await db.execute(select(func.count(Refunds.id)).where(Refunds.created_at.between(start, end)))).scalar()
        return {
            "from": start, "to": end,
            "users": {"by_role": role_counts, "verified_by_role": verified, "new_in_period": new_users,
                      "active_in_period": await self._active_users(db, start, end)},
            "orders": {"by_status": status_counts, "total": total_orders,
                       "completed_value": money(completed_value[0]), "platform_revenue": money(completed_value[1])},
            "negotiation": await self._negotiation_metrics(db, start, end),
            "rates": {
                "cancellation_rate_percent": _pct(status_counts.get(CANCELLED, 0), total_orders),
                "dispute_rate_percent": _pct(disputes, total_orders),
                "refund_rate_percent": _pct(refunds, total_orders),
                "payment_success_rate_percent": _pct(payments.get(paid_id, 0),
                                                     payments.get(paid_id, 0) + payments.get(failed_id, 0)),
            },
            "suspicious_activity": "See GET /api/admin/monitoring",
        }

    async def _active_users(self, db, start, end) -> dict:
        farmers, vendors = await self._active_sets(db, start, end)
        return {"farmers": len(farmers), "vendors": len(vendors)}

    async def _active_sets(self, db, start, end) -> tuple[set, set]:
        farmers = set((await db.execute(select(FarmerInventory.created_by).where(
            or_(FarmerInventory.created_at.between(start, end), FarmerInventory.updated_at.between(start, end))))).scalars().all())
        farmers |= set((await db.execute(select(Orders.farmer).where(Orders.created_at.between(start, end)))).scalars().all())
        farmers |= set((await db.execute(select(Negotiations.farmer).where(Negotiations.updated_at.between(start, end)))).scalars().all())
        vendors = set((await db.execute(select(Orders.vendor).where(Orders.created_at.between(start, end)))).scalars().all())
        vendors |= set((await db.execute(select(Negotiations.vendor).where(Negotiations.updated_at.between(start, end)))).scalars().all())
        return farmers, vendors

    async def _negotiation_metrics(self, db, start, end) -> dict:
        statuses = dict((await db.execute(
            select(Negotiations.status, func.count(Negotiations.id))
            .where(Negotiations.created_at.between(start, end)).group_by(Negotiations.status)
        )).all())
        total = sum(statuses.values())
        offer_counts = (await db.execute(
            select(func.avg(func.coalesce(select(func.count(Offers.id)).where(Offers.negotiation_id == Negotiations.id)
                                          .scalar_subquery(), 0)))
            .where(Negotiations.status == ACCEPTED, Negotiations.created_at.between(start, end))
        )).scalar()
        agreement_minutes = (await db.execute(
            select(func.percentile_cont(0.5).within_group(
                func.extract("epoch", Negotiations.closed_at - Negotiations.created_at) / 60))
            .where(Negotiations.status == ACCEPTED, Negotiations.created_at.between(start, end))
        )).scalar()
        offer_status = dict((await db.execute(
            select(Offers.status, func.count(Offers.id)).where(Offers.created_at.between(start, end)).group_by(Offers.status)
        )).all())
        decided = sum(offer_status.get(s, 0) for s in (ACCEPTED, REJECTED, COUNTERED, EXPIRED))
        return {
            "negotiations_started": total,
            "negotiation_to_order_percent": _pct(statuses.get(ACCEPTED, 0), total),
            "abandonment_percent": _pct(statuses.get(EXPIRED, 0) + statuses.get(NEG_CANCELLED, 0), total),
            "average_offers_per_agreed_negotiation": _f(offer_counts),
            "median_minutes_to_agreement": _f(agreement_minutes),
            "offer_acceptance_rate_percent": _pct(offer_status.get(ACCEPTED, 0), decided),
            "offer_rejection_rate_percent": _pct(offer_status.get(REJECTED, 0), decided),
            "counteroffer_frequency_percent": _pct(offer_status.get(COUNTERED, 0), decided),
        }

    async def success_metrics(self, db: AsyncSession, weeks: int = 4) -> dict:
        """The marketplace outcome metrics from the product spec (section 27)."""
        end = utcnow()
        start = end - timedelta(weeks=weeks)
        prev_start = start - timedelta(weeks=weeks)
        cur_farmers, cur_vendors = await self._active_sets(db, start, end)
        prev_farmers, prev_vendors = await self._active_sets(db, prev_start, start)
        active = {"farmers": len(cur_farmers), "vendors": len(cur_vendors)}
        listings = (await db.execute(select(FarmerInventory.id, FarmerInventory.created_at, FarmerInventory.sold_qty)
                                     .where(FarmerInventory.created_at.between(start, end)))).all()
        first_offer = dict((await db.execute(
            select(Negotiations.listing_id, func.min(Negotiations.created_at)).group_by(Negotiations.listing_id)
        )).all())
        with_offer = [l for l in listings if l.id in first_offer]
        hours_to_first = sorted((first_offer[l.id] - l.created_at).total_seconds() / 3600 for l in with_offer
                                if l.created_at and first_offer[l.id] >= l.created_at)
        median_hours = hours_to_first[len(hours_to_first) // 2] if hours_to_first else None

        status_counts = dict((await db.execute(
            select(Miscellaneous_Data.value, func.count(Orders.id)).join(Miscellaneous_Data, Orders.status == Miscellaneous_Data.id)
            .where(Orders.created_at.between(start, end)).group_by(Miscellaneous_Data.value)
        )).all())
        total_orders = sum(status_counts.values())
        on_time = (await db.execute(select(
            func.count(Orders.id).filter(func.date(Orders.delivered_at) <= Orders.expected_delivery_date),
            func.count(Orders.id).filter(Orders.expected_delivery_date.is_not(None), Orders.delivered_at.is_not(None)),
        ).where(Orders.created_at.between(start, end)))).one()
        vendor_orders = (await db.execute(select(Orders.vendor, func.count(Orders.id))
                                          .where(Orders.created_at.between(start, end)).group_by(Orders.vendor))).all()
        farmer_orders = (await db.execute(select(Orders.farmer, func.count(Orders.id))
                                          .where(Orders.created_at.between(start, end)).group_by(Orders.farmer))).all()
        aov = (await db.execute(select(func.avg(Orders.total_price)).join(Miscellaneous_Data, Orders.status == Miscellaneous_Data.id)
                                .where(Orders.created_at.between(start, end), Miscellaneous_Data.value.in_(DEAL_STATUSES)))).scalar()
        admin = await self.admin_report(db, start.date(), end.date())
        return {
            "window_weeks": weeks,
            "liquidity": {
                "active_farmers": active["farmers"], "active_vendors": active["vendors"],
                "listings_with_at_least_one_offer_percent": _pct(len(with_offer), len(listings)),
                "listings_sold_percent": _pct(sum(1 for l in listings if l.sold_qty and D(l.sold_qty) > 0), len(listings)),
                "median_hours_listing_to_first_offer": round(median_hours, 1) if median_hours is not None else None,
            },
            "negotiation_effectiveness": admin["negotiation"],
            "transaction_reliability": {
                "order_completion_rate_percent": _pct(status_counts.get(COMPLETED, 0), total_orders),
                "on_time_fulfilment_percent": _pct(on_time[0], on_time[1]),
                **admin["rates"],
            },
            "user_value": {
                "repeat_vendor_purchase_rate_percent": _pct(sum(1 for _, n in vendor_orders if n >= 2), len(vendor_orders)),
                "repeat_farmer_sales_rate_percent": _pct(sum(1 for _, n in farmer_orders if n >= 2), len(farmer_orders)),
                "farmer_retention_percent": _pct(len(cur_farmers & prev_farmers), len(prev_farmers)),
                "vendor_retention_percent": _pct(len(cur_vendors & prev_vendors), len(prev_vendors)),
                "average_order_value": money(aov) if aov is not None else None,
            },
            "note": "Retention = users active in the previous window who are also active in this one. Price comparisons "
                    "must account for variety, grade, quantity, location and time.",
        }
