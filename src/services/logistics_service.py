from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import audit
from src.core.crypto import hash_secret, verify_secret
from src.core.money import D
from src.core.otp import generate_code
from src.data_models.logistics_model import Shipments
from src.data_models.orders_model import (
    Orders, PICKUP, VENDOR_TRANSPORT, READY_FOR_PICKUP, IN_TRANSIT, DELIVERED, DELIVERY_FAILED, CONFIRMED, PREPARING,
)
from src.helpers.serializers import model_to_dict
from src.services import order_core
from src.services.files_service import FilesService
from src.services.notifications_service import notify_user

DELIVERY_CODE_DAYS = 7


class LogisticsService:
    async def _shipment(self, db: AsyncSession, order: Orders) -> Shipments:
        shipment = (await db.execute(
            select(Shipments).where(Shipments.order_id == order.id).with_for_update()
        )).scalar_one_or_none()
        if not shipment:
            shipment = Shipments(order_id=order.id, mode=order.fulfillment_mode or PICKUP, status="planned",
                                 reschedule_count=0, created_at=datetime.utcnow())
            db.add(shipment)
            await db.flush()
        return shipment

    @staticmethod
    def _view(shipment: Shipments) -> dict:
        data = model_to_dict(shipment)
        data.pop("delivery_otp_hash", None)
        return data

    @staticmethod
    async def issue_delivery_code(db: AsyncSession, order: Orders):
        """Give the vendor a one-time code to hand over only when the produce is received."""
        shipment = (await db.execute(select(Shipments).where(Shipments.order_id == order.id))).scalar_one_or_none()
        if not shipment:
            return
        code = generate_code()
        shipment.delivery_otp_hash = hash_secret(f"delivery:{order.id}:{code}")
        shipment.delivery_otp_expires_at = datetime.utcnow() + timedelta(days=DELIVERY_CODE_DAYS)
        await notify_user(db, order.vendor, "delivery_code", {"code": code, "order_number": order.order_number},
                          ref_type="order", ref_id=order.id, category="security")

    async def get(self, user, order_id: int, db: AsyncSession) -> dict:
        order = (await db.execute(select(Orders).where(Orders.id == order_id))).scalar_one_or_none()
        if not order or user.id not in (order.farmer, order.vendor):
            raise HTTPException(status_code=404, detail="Order not found.")
        shipment = (await db.execute(select(Shipments).where(Shipments.order_id == order.id))).scalar_one_or_none()
        return self._view(shipment) if shipment else {}

    async def update_plan(self, user, order_id: int, payload, db: AsyncSession) -> dict:
        """Pickup/delivery schedule, addresses, contacts, transporter and transport charge."""
        order = await order_core.lock_order(db, order_id)
        party = order_core.party_of(order, user.id)
        current = await order_core.status_of(db, order)
        if current not in ("pending_confirmation", CONFIRMED, PREPARING, READY_FOR_PICKUP, DELIVERY_FAILED):
            raise HTTPException(status_code=409, detail="The shipment can't be changed at this stage.")
        shipment = await self._shipment(db, order)
        # The party responsible for transport sets the transporter details.
        transport_owner = "vendor" if order.fulfillment_mode in (PICKUP, VENDOR_TRANSPORT) else "farmer"
        fields = payload.model_dump(exclude_unset=True)
        if ({"transporter_name", "vehicle_number"} & fields.keys()) and party != transport_owner:
            raise HTTPException(status_code=403, detail=f"The {transport_owner} arranges transport for this order.")
        rescheduled = shipment.pickup_date is not None and "pickup_date" in fields and fields["pickup_date"] != shipment.pickup_date
        for field, value in fields.items():
            setattr(shipment, field, value)
        if rescheduled:
            shipment.reschedule_count += 1
        shipment.updated_at = datetime.utcnow()
        other = order.vendor if party == "farmer" else order.farmer
        if "pickup_date" in fields and shipment.pickup_date:
            await notify_user(db, other, "pickup_scheduled",
                              {"order_number": order.order_number, "date": shipment.pickup_date.isoformat()},
                              ref_type="order", ref_id=order.id)
        audit(db, "shipment.updated", "shipment", shipment.id, actor_id=user.id, actor_role=party, after=fields)
        await db.commit()
        return self._view(shipment)

    async def dispatch(self, user, order_id: int, payload, db: AsyncSession) -> dict:
        """Record pickup/dispatch (with optional photo proof) and move the order in transit."""
        order = await order_core.lock_order(db, order_id)
        shipment = await self._shipment(db, order)
        if payload.proof_file_id:
            await FilesService.require_owned(db, [payload.proof_file_id], user.id, {"pickup_proof"})
            shipment.pickup_proof_file_id = payload.proof_file_id
        await order_core.transition(db, order, IN_TRANSIT, user.id, note=payload.note or "dispatched")
        shipment.status = "in_transit"
        shipment.dispatched_at = datetime.utcnow()
        shipment.transporter_name = payload.transporter_name or shipment.transporter_name
        shipment.vehicle_number = payload.vehicle_number or shipment.vehicle_number
        if not shipment.delivery_otp_hash:
            await self.issue_delivery_code(db, order)
        await db.commit()
        return self._view(shipment)

    async def confirm_delivery(self, user, order_id: int, payload, db: AsyncSession) -> dict:
        """
        Proof of delivery. The farmer/transporter enters the vendor's delivery code, or the vendor
        confirms receipt directly. Accepted quantity/quality and a photo can be recorded.
        """
        order = await order_core.lock_order(db, order_id)
        party = order_core.party_of(order, user.id)
        shipment = await self._shipment(db, order)
        if party == "farmer":
            if not payload.delivery_code:
                raise HTTPException(status_code=422, detail="Enter the delivery code the vendor received.")
            if not shipment.delivery_otp_hash or (shipment.delivery_otp_expires_at and shipment.delivery_otp_expires_at < datetime.utcnow()):
                raise HTTPException(status_code=409, detail="The delivery code has expired; ask the vendor to confirm receipt.")
            if not verify_secret(f"delivery:{order.id}:{payload.delivery_code}", shipment.delivery_otp_hash):
                raise HTTPException(status_code=400, detail="Incorrect delivery code.")
        if payload.proof_file_id:
            await FilesService.require_owned(db, [payload.proof_file_id], user.id, {"delivery_proof"})
            shipment.delivery_proof_file_id = payload.proof_file_id
        if payload.accepted_quantity is not None and D(payload.accepted_quantity) > D(order.quantity_kg):
            raise HTTPException(status_code=422, detail="Accepted quantity can't exceed the ordered quantity.")
        await order_core.transition(db, order, DELIVERED, user.id, note=payload.notes or "delivered")
        now = datetime.utcnow()
        shipment.status = "delivered"
        shipment.delivered_at = now
        shipment.receiver_name = payload.receiver_name
        shipment.accepted_quantity = D(payload.accepted_quantity) if payload.accepted_quantity is not None else order.quantity_kg
        shipment.quality_accepted = payload.quality_accepted
        shipment.delivery_notes = payload.notes
        shipment.delivery_otp_hash = None
        quality_issue = payload.quality_accepted is False or (
            payload.accepted_quantity is not None and D(payload.accepted_quantity) < D(order.quantity_kg)
        )
        await db.commit()
        result = self._view(shipment)
        if quality_issue:
            result["next_step"] = "Quantity or quality was not fully accepted. Raise a dispute: POST /api/disputes."
        return result

    async def report_failure(self, user, order_id: int, payload, db: AsyncSession) -> dict:
        order = await order_core.lock_order(db, order_id)
        shipment = await self._shipment(db, order)
        await order_core.transition(db, order, DELIVERY_FAILED, user.id, note=payload.reason)
        shipment.status = "failed"
        shipment.failure_reason = payload.reason
        shipment.updated_at = datetime.utcnow()
        await db.commit()
        return self._view(shipment)

    async def reschedule(self, user, order_id: int, payload, db: AsyncSession) -> dict:
        """After a failed delivery: set a new date and resume (farmer)."""
        order = await order_core.lock_order(db, order_id)
        shipment = await self._shipment(db, order)
        target = READY_FOR_PICKUP if order.fulfillment_mode in (PICKUP, VENDOR_TRANSPORT) else IN_TRANSIT
        await order_core.transition(db, order, target, user.id, note=f"rescheduled to {payload.pickup_date}")
        shipment.pickup_date = payload.pickup_date
        shipment.window_start = payload.window_start
        shipment.window_end = payload.window_end
        shipment.reschedule_count += 1
        shipment.status = "planned" if target == READY_FOR_PICKUP else "in_transit"
        shipment.updated_at = datetime.utcnow()
        await self.issue_delivery_code(db, order)
        await notify_user(db, order.vendor, "pickup_scheduled",
                          {"order_number": order.order_number, "date": payload.pickup_date.isoformat()},
                          ref_type="order", ref_id=order.id)
        await db.commit()
        return self._view(shipment)
