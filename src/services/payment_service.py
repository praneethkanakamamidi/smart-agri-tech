"""
Payments. Amounts are always computed on the server from the order; a client never chooses
how much to pay. Payment success is confirmed server-side (signature check, signed webhook or
reconciliation against the gateway) - never by a client-side success screen.
"""
import asyncio
import hashlib
import hmac
import json
import os
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import audit
from src.core.lookups import misc_id, misc_value
from src.core.money import D, money, to_paise
from src.data_models.orders_model import (
    Orders, PARTIAL_ADVANCE, CASH_ON_DELIVERY, CANCELLED, REFUND_PENDING, REFUNDED,
    PENDING_CONFIRMATION,
)
from src.data_models.transactions_model import Transactions, Refunds, Settlements, WebhookEvents, PAYMENT_STATE_NAMES
from src.helpers.serializers import model_to_dict
from src.services import order_core, invoices_service
from src.services.notifications_service import notify_user
from src.core.clock import utcnow

PENDING_REUSE_MINUTES = 30


def _razorpay_client():
    key_id, key_secret = os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret:
        raise HTTPException(status_code=503, detail="Online payments are not configured.")
    import razorpay

    return razorpay.Client(auth=(key_id, key_secret))


async def _mark_paid(db: AsyncSession, txn: Transactions, payment_id: str | None, signature: str | None, via: str):
    """Idempotent: a transaction already marked paid is left untouched."""
    paid_id = await misc_id(db, "payment_status", "paid")
    if txn.status == paid_id:
        return False
    txn.status = paid_id
    txn.razorpay_payment_id = payment_id or txn.razorpay_payment_id
    txn.razorpay_signature = signature or txn.razorpay_signature
    txn.verified_via = via
    txn.updated_at = utcnow()
    order = (await db.execute(select(Orders).where(Orders.id == txn.order_id))).scalar_one()
    await invoices_service.issue(db, order, "payment_receipt", txn)
    audit(db, "payment.succeeded", "transaction", txn.id, after={"amount": txn.amount_paid, "via": via})
    for party_id in (order.farmer, order.vendor):
        await notify_user(db, party_id, "payment_received",
                          {"amount": txn.amount_paid, "order_number": order.order_number},
                          ref_type="order", ref_id=order.id)
    return True


async def _mark_failed(db: AsyncSession, txn: Transactions, reason: str | None):
    if await misc_value(db, txn.status) in ("paid", "failed"):
        return
    txn.status = await misc_id(db, "payment_status", "failed")
    txn.failure_reason = (reason or "payment failed")[:255]
    txn.updated_at = utcnow()
    order = (await db.execute(select(Orders).where(Orders.id == txn.order_id))).scalar_one()
    await notify_user(db, order.vendor, "payment_failed", {"amount": txn.amount_paid, "order_number": order.order_number},
                      ref_type="order", ref_id=order.id)
    audit(db, "payment.failed", "transaction", txn.id, after={"reason": reason})


class PaymentsService:
    async def _vendor_order(self, db: AsyncSession, order_id: int, vendor_id: int) -> Orders:
        order = await order_core.lock_order(db, order_id)
        if order.vendor != vendor_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        return order

    async def summary(self, user_id: int, order_id: int, db: AsyncSession, is_admin: bool = False) -> dict:
        order = (await db.execute(select(Orders).where(Orders.id == order_id))).scalar_one_or_none()
        if not order or (not is_admin and user_id not in (order.farmer, order.vendor)):
            raise HTTPException(status_code=404, detail="Order not found")
        summary = await order_core.money_summary(db, order)
        txns = (await db.execute(select(Transactions).where(Transactions.order_id == order.id)
                                 .order_by(Transactions.created_at))).scalars().all()
        refunds = (await db.execute(select(Refunds).where(Refunds.order_id == order.id))).scalars().all()
        breakdown = {k: (order.terms_snapshot or {}).get(k) for k in (
            "subtotal", "packaging_charge", "transport_charge", "discount_amount", "platform_fee", "tax_amount",
            "total_payable", "fee_payer",
        )}
        txn_views = []
        for t in txns:
            view = model_to_dict(t)
            view.pop("razorpay_signature", None)
            view["state"] = PAYMENT_STATE_NAMES.get(await misc_value(db, t.status), "PENDING")
            txn_views.append(view)
        return {**summary, "breakdown": breakdown, "transactions": txn_views,
                "refunds": [model_to_dict(r) for r in refunds]}

    async def _amount_for(self, db: AsyncSession, order: Orders, purpose: str) -> tuple[str, D]:
        summary = await order_core.money_summary(db, order)
        if summary["outstanding"] <= 0:
            raise HTTPException(status_code=409, detail="Nothing is outstanding on this order.")
        if purpose == "auto":
            purpose = "advance" if order.payment_terms == PARTIAL_ADVANCE and summary["advance_outstanding"] else "full"
        if purpose == "advance":
            if order.payment_terms != PARTIAL_ADVANCE or not summary["advance_outstanding"]:
                raise HTTPException(status_code=422, detail="No advance is due on this order.")
            return "advance", summary["advance_outstanding"]
        return ("balance" if summary["paid"] > 0 else "full"), summary["outstanding"]

    async def create_payment_order(self, payload, vendor_id: int, db: AsyncSession):
        order = await self._vendor_order(db, payload.order_id, vendor_id)
        current = await order_core.status_of(db, order)
        if current in (CANCELLED, REFUND_PENDING, REFUNDED, PENDING_CONFIRMATION):
            raise HTTPException(status_code=409, detail=f"Payments can't be made while the order is {current}.")
        if order.payment_terms == CASH_ON_DELIVERY:
            raise HTTPException(status_code=409, detail="This order is paid in cash on delivery.")
        purpose, amount = await self._amount_for(db, order, payload.purpose)

        # Duplicate protection: reuse a recent unpaid gateway order for the same amount.
        pending_id = await misc_id(db, "payment_status", "pending")
        recent = (await db.execute(select(Transactions).where(
            Transactions.order_id == order.id, Transactions.status == pending_id,
            Transactions.amount_paid == amount, Transactions.purpose == purpose,
            Transactions.created_at >= utcnow() - timedelta(minutes=PENDING_REUSE_MINUTES),
        ))).scalars().first()
        if recent:
            return {"success": True, "message": "Existing payment order reused", "razorpay_order_id": recent.razorpay_order_id,
                    "amount": recent.amount_paid, "currency": recent.currency, "purpose": purpose,
                    "key_id": os.getenv("RAZORPAY_KEY_ID")}

        client = _razorpay_client()
        try:
            razorpay_order = await asyncio.to_thread(client.order.create, {
                "amount": to_paise(amount), "currency": payload.currency,
                "receipt": f"{order.order_number}-{purpose}"[:40], "payment_capture": 1,
                "notes": {"order_id": str(order.id), "purpose": purpose},
            })
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Payment gateway error: {e}")
        txn = Transactions(
            order_id=order.id, razorpay_order_id=razorpay_order["id"], amount_paid=amount, currency=payload.currency,
            status=pending_id, payment_method="gateway", purpose=purpose, created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(txn)
        audit(db, "payment.initiated", "order", order.id, actor_id=vendor_id, actor_role="vendor",
              after={"amount": amount, "purpose": purpose, "razorpay_order_id": razorpay_order["id"]})
        await db.commit()
        return {"success": True, "message": "Payment order created successfully",
                "razorpay_order_id": razorpay_order["id"], "amount": amount, "currency": payload.currency,
                "purpose": purpose, "key_id": os.getenv("RAZORPAY_KEY_ID")}

    async def verify_payment(self, payload, vendor_id: int, db: AsyncSession):
        client = _razorpay_client()
        try:
            client.utility.verify_payment_signature({
                "razorpay_order_id": payload.razorpay_order_id,
                "razorpay_payment_id": payload.razorpay_payment_id,
                "razorpay_signature": payload.razorpay_signature,
            })
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payment signature")
        txn = (await db.execute(select(Transactions).where(
            Transactions.razorpay_order_id == payload.razorpay_order_id
        ).with_for_update())).scalar_one_or_none()
        order = (await db.execute(select(Orders).where(Orders.id == txn.order_id))).scalar_one_or_none() if txn else None
        if not txn or not order or order.vendor != vendor_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
        changed = await _mark_paid(db, txn, payload.razorpay_payment_id, payload.razorpay_signature, "client_signature")
        await db.commit()
        return {"success": True, "message": "Payment verified successfully" if changed else "Payment already recorded"}

    async def handle_webhook(self, raw_body: bytes, signature: str | None, db: AsyncSession) -> dict:
        secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")
        if not secret:
            raise HTTPException(status_code=503, detail="Webhook secret is not configured.")
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        if not signature or not hmac.compare_digest(expected, signature):
            raise HTTPException(status_code=400, detail="Invalid webhook signature.")
        event = json.loads(raw_body)
        event_id = event.get("id") or hashlib.sha256(raw_body).hexdigest()
        if (await db.execute(select(WebhookEvents.id).where(WebhookEvents.event_id == event_id))).first():
            return {"status": "duplicate"}
        record = WebhookEvents(provider="razorpay", event_id=event_id, event_type=event.get("event"),
                               payload=event, received_at=utcnow(), status="ignored")
        db.add(record)
        event_type = event.get("event", "")
        payload = event.get("payload", {})
        try:
            if event_type in ("payment.captured", "order.paid", "payment.failed"):
                payment = payload.get("payment", {}).get("entity", {})
                rzp_order_id = payment.get("order_id") or payload.get("order", {}).get("entity", {}).get("id")
                txn = (await db.execute(select(Transactions).where(
                    Transactions.razorpay_order_id == rzp_order_id
                ).with_for_update())).scalar_one_or_none()
                if txn:
                    if event_type == "payment.failed":
                        await _mark_failed(db, txn, payment.get("error_description"))
                    elif to_paise(txn.amount_paid) == int(payment.get("amount", to_paise(txn.amount_paid))):
                        await _mark_paid(db, txn, payment.get("id"), None, "webhook")
                    else:
                        record.error = "amount mismatch"
                    record.status = "processed"
            elif event_type in ("refund.processed", "refund.failed"):
                entity = payload.get("refund", {}).get("entity", {})
                refund = (await db.execute(select(Refunds).where(
                    Refunds.gateway_refund_id == entity.get("id")
                ).with_for_update())).scalar_one_or_none()
                if refund:
                    await self._finish_refund(db, refund, event_type == "refund.processed", entity.get("id"))
                    record.status = "processed"
        except HTTPException as e:
            record.status, record.error = "failed", str(e.detail)[:255]
        await db.commit()
        return {"status": record.status}

    async def reconcile(self, db: AsyncSession, older_than_minutes: int = 5) -> dict:
        """Check unpaid gateway orders against Razorpay and record the true outcome."""
        client = _razorpay_client()
        pending_id = await misc_id(db, "payment_status", "pending")
        txns = (await db.execute(select(Transactions).where(
            Transactions.status == pending_id, Transactions.payment_method == "gateway",
            Transactions.created_at <= utcnow() - timedelta(minutes=older_than_minutes),
        ).limit(200))).scalars().all()
        updated = {"paid": 0, "failed": 0, "unchanged": 0}
        for txn in txns:
            try:
                payments = await asyncio.to_thread(client.order.payments, txn.razorpay_order_id)
            except Exception:
                updated["unchanged"] += 1
                continue
            items = payments.get("items", [])
            captured = next((p for p in items if p.get("status") == "captured"), None)
            if captured:
                await _mark_paid(db, txn, captured.get("id"), None, "reconciliation")
                updated["paid"] += 1
            elif items and all(p.get("status") == "failed" for p in items):
                await _mark_failed(db, txn, items[-1].get("error_description"))
                updated["failed"] += 1
            else:
                updated["unchanged"] += 1
        await db.commit()
        return {"checked": len(txns), **updated}

    async def record_manual_payment(self, farmer_id: int, order_id: int, payload, db: AsyncSession) -> dict:
        order = await order_core.lock_order(db, order_id)
        if order.farmer != farmer_id:
            raise HTTPException(status_code=404, detail="Order not found")
        current = await order_core.status_of(db, order)
        if current in (CANCELLED, REFUND_PENDING, REFUNDED, PENDING_CONFIRMATION):
            raise HTTPException(status_code=409, detail=f"Payments can't be recorded while the order is {current}.")
        summary = await order_core.money_summary(db, order)
        amount = money(payload.amount)
        if amount > summary["outstanding"]:
            raise HTTPException(status_code=422, detail=f"Only ₹{summary['outstanding']} is outstanding.")
        now = utcnow()
        txn = Transactions(
            order_id=order.id, amount_paid=amount, currency="INR", payment_method=payload.method,
            purpose="balance" if summary["paid"] > 0 else "full", reference=payload.reference,
            status=await misc_id(db, "payment_status", "pending"), recorded_by=farmer_id,
            created_at=now, updated_at=now,
        )
        db.add(txn)
        await db.flush()
        await _mark_paid(db, txn, None, None, "farmer_confirmation")
        await notify_user(db, order.vendor, "cash_recorded", {"amount": amount, "order_number": order.order_number},
                          ref_type="order", ref_id=order.id)
        await db.commit()
        return {"success": "Payment recorded.", "transaction_id": txn.id,
                "outstanding": (await order_core.money_summary(db, order))["outstanding"]}

    # ---- refunds ---------------------------------------------------------------------

    async def _finish_refund(self, db: AsyncSession, refund: Refunds, succeeded: bool, reference: str | None):
        if refund.status != "REFUND_PENDING":
            return
        refund.status = "REFUNDED" if succeeded else "FAILED"
        refund.processed_at = utcnow()
        refund.reference = reference or refund.reference
        order = await order_core.lock_order(db, refund.order_id)
        if succeeded:
            pending_left = (await db.execute(select(Refunds.id).where(
                Refunds.order_id == order.id, Refunds.status == "REFUND_PENDING", Refunds.id != refund.id
            ))).first()
            if not pending_left and await order_core.status_of(db, order) == REFUND_PENDING:
                await order_core.transition(db, order, REFUNDED, None, note="refund processed", skip_payment_gate=True)
        for party_id in (order.vendor, order.farmer):
            await notify_user(db, party_id, "refund_status",
                              {"order_number": order.order_number, "amount": refund.amount,
                               "status": "completed" if succeeded else "failed"},
                              ref_type="order", ref_id=order.id)
        audit(db, "refund.processed" if succeeded else "refund.failed", "refund", refund.id)

    async def process_refund(self, admin_id: int, refund_id: int, db: AsyncSession) -> dict:
        """Send a pending refund to the gateway (for gateway payments)."""
        refund = (await db.execute(select(Refunds).where(Refunds.id == refund_id).with_for_update())).scalar_one_or_none()
        if not refund or refund.status != "REFUND_PENDING":
            raise HTTPException(status_code=404, detail="No pending refund with that id.")
        txn = (await db.execute(select(Transactions).where(Transactions.id == refund.transaction_id))).scalar_one_or_none() \
            if refund.transaction_id else None
        if not txn or txn.payment_method != "gateway" or not txn.razorpay_payment_id:
            raise HTTPException(status_code=409, detail="This was not a gateway payment; refund it manually and mark it refunded.")
        if refund.gateway_refund_id:
            return {"success": "Refund already sent to the gateway.", "gateway_refund_id": refund.gateway_refund_id}
        client = _razorpay_client()
        try:
            result = await asyncio.to_thread(client.payment.refund, txn.razorpay_payment_id, {"amount": to_paise(refund.amount)})
        except Exception as e:
            refund.failure_reason = str(e)[:255]
            await db.commit()
            raise HTTPException(status_code=502, detail=f"Gateway refund failed: {e}")
        refund.gateway_refund_id = result.get("id")
        if result.get("status") == "processed":
            await self._finish_refund(db, refund, True, result.get("id"))
        audit(db, "refund.sent_to_gateway", "refund", refund.id, actor_id=admin_id, actor_role="admin")
        await db.commit()
        return {"success": "Refund submitted to the gateway.", "gateway_refund_id": refund.gateway_refund_id}

    async def mark_refunded(self, admin_id: int, refund_id: int, reference: str, db: AsyncSession) -> dict:
        refund = (await db.execute(select(Refunds).where(Refunds.id == refund_id).with_for_update())).scalar_one_or_none()
        if not refund or refund.status != "REFUND_PENDING":
            raise HTTPException(status_code=404, detail="No pending refund with that id.")
        await self._finish_refund(db, refund, True, reference)
        audit(db, "refund.marked_refunded", "refund", refund.id, actor_id=admin_id, actor_role="admin",
              after={"reference": reference})
        await db.commit()
        return {"success": "Refund recorded as completed."}

    async def create_refund(self, admin_id: int, order_id: int, payload, db: AsyncSession) -> dict:
        order = await order_core.lock_order(db, order_id)
        refund = await order_core.refund_if_paid(db, order, admin_id, payload.reason, payload.amount)
        if not refund:
            raise HTTPException(status_code=409, detail="Nothing has been paid on this order.")
        audit(db, "refund.created", "order", order.id, actor_id=admin_id, actor_role="admin",
              after={"amount": refund.amount, "reason": payload.reason})
        await db.commit()
        return {"success": "Refund created.", "refund_id": refund.id, "amount": refund.amount}

    # ---- settlements ---------------------------------------------------------------------

    async def farmer_settlements(self, farmer_id: int, db: AsyncSession) -> dict:
        rows = (await db.execute(select(Settlements, Orders.order_number).join(Orders, Settlements.order_id == Orders.id)
                                 .where(Settlements.farmer == farmer_id).order_by(Settlements.created_at.desc()))).all()
        pending = sum((D(s.net_amount) for s, _ in rows if s.status == "pending"), D(0))
        paid = sum((D(s.net_amount) for s, _ in rows if s.status == "paid"), D(0))
        return {"pending_payout": money(pending), "paid_out": money(paid),
                "settlements": [model_to_dict(s, order_number=n) for s, n in rows]}

    async def mark_settlement_paid(self, admin_id: int, settlement_id: int, reference: str, db: AsyncSession) -> dict:
        settlement = (await db.execute(select(Settlements).where(Settlements.id == settlement_id).with_for_update())).scalar_one_or_none()
        if not settlement or settlement.status != "pending":
            raise HTTPException(status_code=404, detail="No pending settlement with that id.")
        settlement.status = "paid"
        settlement.payout_reference = reference
        settlement.paid_at = utcnow()
        order = (await db.execute(select(Orders).where(Orders.id == settlement.order_id))).scalar_one()
        await notify_user(db, settlement.farmer, "settlement_paid",
                          {"amount": settlement.net_amount, "order_number": order.order_number},
                          ref_type="order", ref_id=order.id)
        audit(db, "settlement.paid", "settlement", settlement.id, actor_id=admin_id, actor_role="admin",
              after={"reference": reference, "amount": settlement.net_amount})
        await db.commit()
        return {"success": "Settlement marked as paid."}
