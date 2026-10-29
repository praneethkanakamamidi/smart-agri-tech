"""
Home-screen summaries. Booked order value, realised (completed) sales and cash actually
received are reported separately and never mixed.
"""

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.lookups import misc_id
from src.core.money import D, money
from src.data_models.buy_requests_model import BuyRequests, BuyRequestResponses
from src.data_models.crop_alerts_model import CropAlerts
from src.data_models.crops_model import Crops
from src.data_models.farmer_inventory_model import FarmerInventory, ACTIVE, RESERVED
from src.data_models.favourites_model import FavouriteFarmers
from src.data_models.messages_model import Messages
from src.data_models.miscellaneous_model import Miscellaneous_Data
from src.data_models.negotiation_model import Negotiations, Offers, PENDING, NEG_OPEN, ACCEPTED, EXPIRED
from src.data_models.notifications_model import Notifications
from src.data_models.orders_model import (
    Orders, ACTIVE_STATUSES, COMPLETED, DELIVERED, CANCELLED, REFUNDED, REFUND_PENDING, IN_TRANSIT,
    CONFIRMED, PREPARING, READY_FOR_PICKUP, PENDING_CONFIRMATION,
)
from src.data_models.transactions_model import Transactions, Settlements
from src.data_models.users_model import Users
from src.services import order_core
from src.services.reviews_service import ReviewsService
from src.core.clock import utcnow

NOT_BOOKED = (CANCELLED, REFUNDED, REFUND_PENDING, PENDING_CONFIRMATION)


class DashboardService:
    async def _scalar(self, db: AsyncSession, stmt):
        return (await db.execute(stmt)).scalar() or 0

    async def _orders_by_status(self, db: AsyncSession, party_column, user_id: int) -> dict:
        rows = await db.execute(
            select(Miscellaneous_Data.value, func.count(Orders.id))
            .join(Miscellaneous_Data, Orders.status == Miscellaneous_Data.id)
            .where(party_column == user_id).group_by(Miscellaneous_Data.value)
        )
        return dict(rows.all())

    async def _order_value(self, db, party_column, user_id, statuses=None, exclude=None):
        stmt = (select(func.coalesce(func.sum(Orders.total_price), 0))
                .join(Miscellaneous_Data, Orders.status == Miscellaneous_Data.id).where(party_column == user_id))
        if statuses:
            stmt = stmt.where(Miscellaneous_Data.value.in_(statuses))
        if exclude:
            stmt = stmt.where(Miscellaneous_Data.value.not_in(exclude))
        return money((await db.execute(stmt)).scalar())

    async def _cash_received(self, db, party_column, user_id, since=None):
        paid_id = await misc_id(db, "payment_status", "paid")
        stmt = (select(func.coalesce(func.sum(Transactions.amount_paid), 0))
                .join(Orders, Transactions.order_id == Orders.id)
                .where(party_column == user_id, Transactions.status == paid_id))
        if since:
            stmt = stmt.where(Transactions.updated_at >= since)
        return money((await db.execute(stmt)).scalar())

    async def _outstanding(self, db, party_column, user_id):
        statuses = ACTIVE_STATUSES + (DELIVERED,)
        orders = (await db.execute(
            select(Orders).join(Miscellaneous_Data, Orders.status == Miscellaneous_Data.id)
            .where(party_column == user_id, Miscellaneous_Data.value.in_(statuses),
                   Miscellaneous_Data.value != PENDING_CONFIRMATION)
        )).scalars().all()
        total = D(0)
        for order in orders:
            total += (await order_core.money_summary(db, order))["outstanding"]
        return money(total)

    async def _by_crop(self, db, party_column, user_id, limit=5):
        price = func.coalesce(Orders.unit_price, Orders.total_price / func.nullif(Orders.quantity_kg, 0))
        rows = (await db.execute(
            select(Crops.crop_name, Orders.unit, func.count(Orders.id), func.sum(Orders.quantity_kg),
                   func.sum(price * Orders.quantity_kg) / func.nullif(func.sum(Orders.quantity_kg), 0),
                   func.sum(Orders.total_price))
            .join(FarmerInventory, Orders.farmer_inventory == FarmerInventory.id)
            .join(Crops, FarmerInventory.crop == Crops.id)
            .join(Miscellaneous_Data, Orders.status == Miscellaneous_Data.id)
            .where(party_column == user_id, Miscellaneous_Data.value.not_in(NOT_BOOKED))
            .group_by(Crops.crop_name, Orders.unit)
            .order_by(func.count(Orders.id).desc()).limit(limit)
        )).all()
        return [
            {"crop_name": name, "unit": unit, "orders": n, "quantity": qty,
             "average_price": round(float(avg), 2) if avg is not None else None, "value": value}
            for name, unit, n, qty, avg, value in rows
        ]

    async def _common(self, db: AsyncSession, user_id: int) -> dict:
        return {
            "rating": await ReviewsService().get_rating_summary(user_id, db),
            "unread_notifications": await self._scalar(db, select(func.count(Notifications.id)).where(
                Notifications.user_id == user_id, Notifications.is_read.is_(False))),
            "unread_messages": await self._scalar(db, select(func.count(Messages.id)).where(
                Messages.receiver == user_id, Messages.is_read.is_(False))),
        }

    async def _negotiation_counts(self, db, user_id, role_column) -> dict:
        now = utcnow()
        base = (select(func.count(Negotiations.id))
                .join(Offers, Offers.id == Negotiations.current_offer_id, isouter=True)
                .where(role_column == user_id))
        return {
            "active_negotiations": await self._scalar(db, base.where(Negotiations.status.in_((NEG_OPEN, EXPIRED)))),
            "offers_requiring_my_response": await self._scalar(db, base.where(
                Negotiations.status == NEG_OPEN, Offers.status == PENDING, Offers.recipient == user_id,
                Offers.expires_at > now)),
            "my_offers_awaiting_response": await self._scalar(db, base.where(
                Negotiations.status == NEG_OPEN, Offers.status == PENDING, Offers.offered_by == user_id,
                Offers.expires_at > now)),
            "accepted_deals": await self._scalar(db, base.where(Negotiations.status == ACCEPTED)),
        }

    async def farmer_dashboard(self, farmer_id: int, db: AsyncSession):
        month_start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        listings = (await db.execute(
            select(func.count(FarmerInventory.id), func.coalesce(func.sum(FarmerInventory.weight_kg), 0),
                   func.coalesce(func.sum(FarmerInventory.reserved_qty), 0))
            .where(FarmerInventory.created_by == farmer_id, FarmerInventory.status.in_((ACTIVE, RESERVED)),
                   FarmerInventory.deleted_at.is_(None))
        )).one()
        by_status = await self._orders_by_status(db, Orders.farmer, farmer_id)
        settlements = (await db.execute(
            select(func.coalesce(func.sum(Settlements.net_amount), 0)).where(
                Settlements.farmer == farmer_id, Settlements.status == "pending")
        )).scalar()
        dashboard = {
            "active_listings": listings[0],
            "total_available_stock": listings[1],
            "reserved_stock": listings[2],
            **await self._negotiation_counts(db, farmer_id, Negotiations.farmer),
            "orders_awaiting_my_confirmation": await self._scalar(db, select(func.count(Orders.id))
                .join(Miscellaneous_Data, Orders.status == Miscellaneous_Data.id)
                .where(Orders.farmer == farmer_id, Miscellaneous_Data.value == PENDING_CONFIRMATION,
                       Orders.farmer_confirmed_at.is_(None))),
            "active_orders": sum(by_status.get(s, 0) for s in ACTIVE_STATUSES),
            "completed_orders": by_status.get(COMPLETED, 0) + by_status.get(DELIVERED, 0),
            "orders_by_status": by_status,
            "booked_order_value": await self._order_value(db, Orders.farmer, farmer_id, exclude=NOT_BOOKED),
            "realised_sales_value": await self._order_value(db, Orders.farmer, farmer_id, statuses=(COMPLETED,)),
            "cash_received_total": await self._cash_received(db, Orders.farmer, farmer_id),
            "cash_received_this_month": await self._cash_received(db, Orders.farmer, farmer_id, month_start),
            "pending_payments_from_vendors": await self._outstanding(db, Orders.farmer, farmer_id),
            "pending_payouts": money(settlements),
            "sales_by_produce": await self._by_crop(db, Orders.farmer, farmer_id),
            "pending_quotation_responses": await self._scalar(db, select(func.count(BuyRequestResponses.id)).where(
                BuyRequestResponses.farmer == farmer_id, BuyRequestResponses.status == "pending")),
            "followers": await self._scalar(db, select(func.count(FavouriteFarmers.id)).where(
                FavouriteFarmers.farmer == farmer_id)),
            "definitions": {
                "booked_order_value": "Confirmed and later orders, not yet necessarily delivered or paid.",
                "realised_sales_value": "Completed orders only.",
                "cash_received_total": "Payments actually received (gateway or recorded cash).",
            },
        }
        dashboard.update(await self._common(db, farmer_id))
        return dashboard

    async def vendor_dashboard(self, vendor_id: int, db: AsyncSession):
        month_start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        by_status = await self._orders_by_status(db, Orders.vendor, vendor_id)
        recent = (await db.execute(
            select(Orders).where(Orders.vendor == vendor_id).order_by(Orders.created_at.desc()).limit(5)
        )).scalars().all()
        paid_id = await misc_id(db, "payment_status", "paid")
        top_farmers = (await db.execute(
            select(Users.id, Users.first_name, Users.last_name, func.count(Orders.id), func.sum(Transactions.amount_paid))
            .select_from(Transactions).join(Orders, Transactions.order_id == Orders.id)
            .join(Users, Orders.farmer == Users.id)
            .where(Orders.vendor == vendor_id, Transactions.status == paid_id)
            .group_by(Users.id, Users.first_name, Users.last_name)
            .order_by(func.sum(Transactions.amount_paid).desc()).limit(5)
        )).all()
        dashboard = {
            **await self._negotiation_counts(db, vendor_id, Negotiations.vendor),
            "orders_by_status": by_status,
            "orders_awaiting_fulfilment": sum(by_status.get(s, 0) for s in (CONFIRMED, PREPARING, READY_FOR_PICKUP)),
            "orders_in_transit": by_status.get(IN_TRANSIT, 0),
            "orders_awaiting_my_confirmation": await self._scalar(db, select(func.count(Orders.id))
                .join(Miscellaneous_Data, Orders.status == Miscellaneous_Data.id)
                .where(Orders.vendor == vendor_id, Miscellaneous_Data.value == PENDING_CONFIRMATION,
                       Orders.vendor_confirmed_at.is_(None))),
            "outstanding_payments": await self._outstanding(db, Orders.vendor, vendor_id),
            "total_procurement_spend": await self._cash_received(db, Orders.vendor, vendor_id),
            "spend_this_month": await self._cash_received(db, Orders.vendor, vendor_id, month_start),
            "booked_purchase_value": await self._order_value(db, Orders.vendor, vendor_id, exclude=NOT_BOOKED),
            "frequently_purchased": await self._by_crop(db, Orders.vendor, vendor_id),
            "recent_purchases": [
                {"order_id": o.id, "order_number": o.order_number, "total": o.total_price, "created_at": o.created_at,
                 "crop_name": (o.terms_snapshot or {}).get("produce", {}).get("display_name")}
                for o in recent
            ],
            "top_suppliers": [
                {"farmer_id": fid, "farmer_name": f"{first} {last}".strip(), "orders": n, "spend": spend}
                for fid, first, last, n, spend in top_farmers
            ],
            "favourite_farmers": await self._scalar(db, select(func.count(FavouriteFarmers.id)).where(
                FavouriteFarmers.vendor == vendor_id)),
            "open_buy_requests": await self._scalar(db, select(func.count(BuyRequests.id)).where(
                BuyRequests.vendor == vendor_id, BuyRequests.status == "open")),
            "active_crop_alerts": await self._scalar(db, select(func.count(CropAlerts.id)).where(
                CropAlerts.vendor == vendor_id, CropAlerts.is_active.is_(True))),
        }
        dashboard.update(await self._common(db, vendor_id))
        return dashboard
