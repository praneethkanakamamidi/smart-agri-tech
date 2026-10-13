from datetime import datetime, date

from fastapi import HTTPException
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import audit
from src.core.i18n import status_label
from src.core.lookups import misc_value
from src.core.money import D
from src.data_models.farmer_inventory_model import FarmerInventory
from src.data_models.listing_extras_model import ListingPriceTiers
from src.data_models.logistics_model import Shipments
from src.data_models.miscellaneous_model import Miscellaneous_Data
from src.data_models.negotiation_model import Negotiations
from src.data_models.orders_model import (
    Orders, OrderStatusHistory, OrderAdjustments, PENDING_CONFIRMATION, CONFIRMED, CANCELLED, DELIVERED,
    READY_FOR_PICKUP,
)
from src.data_models.users_model import Users
from src.helpers.serializers import model_to_dict
from src.services import inventory_core, order_core
from src.services.invoices_service import InvoicesService
from src.services.negotiations_service import NegotiationsService
from src.services.notifications_service import notify_user
from src.schemas.negotiations_schema import StartNegotiationSchema


def _name(user):
    return f"{user.first_name} {user.last_name}".strip() if user else None


class OrdersService:
    # ---- creation -------------------------------------------------------------------

    async def direct_order(self, vendor: Users, payload, db: AsyncSession, source: str = "direct") -> dict:
        listing = await inventory_core.lock_listing(db, payload.listing_id)
        quantity = D(payload.quantity)
        price = D(listing.proposed_cost)
        tier = (await db.execute(
            select(ListingPriceTiers).where(ListingPriceTiers.listing_id == listing.id,
                                            ListingPriceTiers.min_quantity <= quantity)
            .order_by(ListingPriceTiers.min_quantity.desc())
        )).scalars().first()
        if tier:
            price = D(tier.price_per_unit)
        order = await order_core.create_order(
            db, listing=listing, vendor_id=vendor.id, quantity=quantity, unit_price=price, source=source,
            accepted_by=vendor.id, fulfillment_mode=payload.fulfillment_mode, payment_terms=payload.payment_terms,
            expected_delivery_date=payload.expected_delivery_date,
            delivery_instructions=payload.delivery_instructions, vendor_confirmed=True, farmer_confirmed=False,
            extra_terms={"price_basis": "quantity_tier" if tier else "asking_price"},
        )
        await db.commit()
        return {"success": "Order placed. The farmer will confirm it.", "order_id": order.id,
                "order_number": order.order_number, "unit_price": order.unit_price,
                "total_payable": order.total_price, "status": PENDING_CONFIRMATION}

    async def reorder(self, vendor: Users, order_id: int, payload, db: AsyncSession) -> dict:
        """Start a new negotiation on the same listing with the last agreed terms as the opening offer."""
        order = (await db.execute(select(Orders).where(Orders.id == order_id))).scalar_one_or_none()
        if not order or order.vendor != vendor.id:
            raise HTTPException(status_code=404, detail="Order not found.")
        start = StartNegotiationSchema(
            listing_id=order.farmer_inventory,
            quantity=payload.quantity or float(order.quantity_kg),
            unit_price=payload.unit_price or float(order.unit_price or order.total_price / order.quantity_kg),
            delivery_preference=order.fulfillment_mode,
            message=payload.message or f"Repeat of order {order.order_number}.",
        )
        result = await NegotiationsService().start(vendor, start, db)
        negotiation = (await db.execute(select(Negotiations).where(Negotiations.id == result["negotiation_id"]))).scalar_one()
        negotiation.source, negotiation.source_ref_id = "reorder", order.id
        await db.commit()
        return {**result, "success": "Reorder sent to the farmer as a new offer."}

    # ---- lifecycle --------------------------------------------------------------------

    async def _locked_party_order(self, db: AsyncSession, order_id: int, user_id: int, is_admin: bool = False) -> Orders:
        order = await order_core.lock_order(db, order_id)
        if not is_admin and user_id not in (order.farmer, order.vendor):
            raise HTTPException(status_code=404, detail="Order not found.")
        return order

    async def confirm(self, user: Users, order_id: int, db: AsyncSession) -> dict:
        order = await self._locked_party_order(db, order_id, user.id)
        result = await order_core.confirm(db, order, user.id)
        await db.commit()
        return {"success": "Order confirmed." if result["status"] == CONFIRMED else "Confirmation recorded.", **result}

    async def change_status(self, user: Users, order_id: int, to_status: str, note: str | None, db: AsyncSession) -> dict:
        order = await self._locked_party_order(db, order_id, user.id)
        if to_status == DELIVERED and user.id == order.farmer:
            raise HTTPException(status_code=409, detail="Farmers confirm delivery with the vendor's delivery code: POST /api/orders/{id}/delivery/confirm.")
        previous = await order_core.transition(db, order, to_status, user.id, note=note)
        if to_status in (READY_FOR_PICKUP,) or (to_status == "in_transit"):
            from src.services.logistics_service import LogisticsService
            await LogisticsService.issue_delivery_code(db, order)
        await db.commit()
        return {"success": f"Order is now {to_status}.", "previous_status": previous, "status": to_status}

    async def cancel(self, user: Users, order_id: int, reason: str, db: AsyncSession, role: str | None = None) -> dict:
        order = await self._locked_party_order(db, order_id, user.id, is_admin=role == "admin")
        result = await order_core.cancel(db, order, user.id, role, reason)
        await db.commit()
        return result

    async def decide_cancel_request(self, farmer: Users, order_id: int, approve: bool, db: AsyncSession) -> dict:
        order = await self._locked_party_order(db, order_id, farmer.id)
        if order.farmer != farmer.id or not order.cancel_requested_by:
            raise HTTPException(status_code=409, detail="There is no cancellation request to decide.")
        reason = order.cancel_request_reason or "requested by vendor"
        order.cancel_requested_by = None
        if approve:
            await order_core.transition(db, order, CANCELLED, farmer.id, note=f"vendor request approved: {reason}")
            await order_core.refund_if_paid(db, order, farmer.id, f"order cancelled: {reason}")
            message = "Cancellation approved."
        else:
            await notify_user(db, order.vendor, "order_status",
                              {"order_number": order.order_number, "status": await order_core.status_of(db, order)},
                              ref_type="order", ref_id=order.id)
            message = "Cancellation request declined; the order continues."
        audit(db, "order.cancel_request_decided", "order", order.id, actor_id=farmer.id, actor_role="farmer",
              after={"approved": approve})
        await db.commit()
        return {"success": message}

    # ---- reads ---------------------------------------------------------------------------

    async def list_orders(
        self, user: Users, db: AsyncSession, role: str | None = None, status: str | None = None,
        date_from: date | None = None, date_to: date | None = None, counterparty_id: int | None = None,
        crop_id: int | None = None, page: int = 1, page_size: int = 20,
    ) -> dict:
        filters = []
        if role == "farmer":
            filters.append(Orders.farmer == user.id)
        elif role == "vendor":
            filters.append(Orders.vendor == user.id)
        else:
            filters.append(or_(Orders.farmer == user.id, Orders.vendor == user.id))
        if status:
            filters.append(Miscellaneous_Data.value == status.lower())
        if date_from:
            filters.append(Orders.created_at >= datetime.combine(date_from, datetime.min.time()))
        if date_to:
            filters.append(Orders.created_at <= datetime.combine(date_to, datetime.max.time()))
        if counterparty_id:
            filters.append(or_(Orders.farmer == counterparty_id, Orders.vendor == counterparty_id))
        if crop_id:
            filters.append(FarmerInventory.crop == crop_id)
        base = (
            select(Orders, Miscellaneous_Data.value)
            .join(Miscellaneous_Data, Orders.status == Miscellaneous_Data.id)
            .join(FarmerInventory, Orders.farmer_inventory == FarmerInventory.id)
            .where(*filters)
        )
        total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
        rows = (await db.execute(
            base.order_by(Orders.created_at.desc(), Orders.id.desc()).limit(page_size).offset((page - 1) * page_size)
        )).all()
        user_ids = {o.farmer for o, _ in rows} | {o.vendor for o, _ in rows}
        names = {u.id: _name(u) for u in (await db.execute(select(Users).where(Users.id.in_(user_ids)))).scalars().all()} if user_ids else {}
        lang = user.preferred_language
        data = []
        for order, status_value in rows:
            summary = await order_core.money_summary(db, order)
            data.append(self._order_row(order, status_value, names, user.id, lang, summary))
        return {"page": page, "page_size": page_size, "total_records": total,
                "total_pages": (total + page_size - 1) // page_size, "data": data}

    def _order_row(self, order, status_value, names, viewer_id, lang, summary) -> dict:
        produce = (order.terms_snapshot or {}).get("produce", {})
        return {
            **model_to_dict(order, terms_snapshot=None),
            "terms_snapshot": None,
            "crop_name": produce.get("display_name"),
            "order_status": status_value,
            "order_status_label": status_label(status_value, lang),
            "my_role": "farmer" if viewer_id == order.farmer else "vendor",
            "farmer_name": names.get(order.farmer),
            "vendor_name": names.get(order.vendor),
            "payment_status": "paid" if summary["outstanding"] == 0 and summary["paid"] > 0 else
                              ("partially_paid" if summary["paid"] > 0 else "pending"),
            "outstanding": summary["outstanding"],
            "awaiting_my_confirmation": status_value == PENDING_CONFIRMATION and (
                (viewer_id == order.farmer and not order.farmer_confirmed_at)
                or (viewer_id == order.vendor and not order.vendor_confirmed_at)
            ),
        }

    async def detail(self, user: Users, order_id: int, db: AsyncSession, is_admin: bool = False) -> dict:
        order = (await db.execute(select(Orders).where(Orders.id == order_id))).scalar_one_or_none()
        if not order or (not is_admin and user.id not in (order.farmer, order.vendor)):
            raise HTTPException(status_code=404, detail="Order not found.")
        status_value = await misc_value(db, order.status)
        names = {u.id: _name(u) for u in (await db.execute(
            select(Users).where(Users.id.in_((order.farmer, order.vendor)))
        )).scalars().all()}
        summary = await order_core.money_summary(db, order)
        history = (await db.execute(
            select(OrderStatusHistory).where(OrderStatusHistory.order_id == order.id).order_by(OrderStatusHistory.id)
        )).scalars().all()
        shipment = (await db.execute(select(Shipments).where(Shipments.order_id == order.id))).scalar_one_or_none()
        adjustments = (await db.execute(select(OrderAdjustments).where(OrderAdjustments.order_id == order.id))).scalars().all()
        lang = user.preferred_language
        shipment_view = None
        if shipment:
            shipment_view = model_to_dict(shipment)
            shipment_view.pop("delivery_otp_hash", None)
        return {
            **self._order_row(order, status_value, names, user.id, lang, summary),
            "terms_snapshot": order.terms_snapshot,
            "money": summary,
            "timeline": [
                {"from": h.from_status, "to": h.to_status, "to_label": status_label(h.to_status, lang),
                 "actor_id": h.actor_id, "note": h.note, "at": h.created_at}
                for h in history
            ],
            "shipment": shipment_view,
            "adjustments": [model_to_dict(a) for a in adjustments],
            "invoices": await InvoicesService().list_for_order(order.id, user.id, True, db),
            "cancellation_request": {
                "requested_by": order.cancel_requested_by, "reason": order.cancel_request_reason,
                "requested_at": order.cancel_requested_at,
            } if order.cancel_requested_by else None,
        }

    # ---- legacy adapters -------------------------------------------------------------------

    async def legacy_status(self, user: Users, payload, db: AsyncSession) -> dict:
        """Maps the old pending/accepted/rejected values onto the new lifecycle."""
        status = (payload.status or "").lower()
        if status in ("accepted", "confirmed"):
            return await self.confirm(user, payload.order_id, db)
        if status in ("rejected", "cancelled"):
            return await self.cancel(user, payload.order_id, f"{status} by user", db)
        if status == "dispatched":
            status = "in_transit"
        return await self.change_status(user, payload.order_id, status, None, db)
