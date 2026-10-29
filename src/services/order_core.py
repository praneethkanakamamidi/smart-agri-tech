"""
Order creation and lifecycle. Every path that creates an order (accepted negotiation, direct
purchase, procurement quote, recurring supply) goes through `create_order`, and every status
change goes through `transition`. Callers commit.
"""
from datetime import timedelta, date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import audit
from src.core.lookups import misc_id, misc_value
from src.core.money import D, money
from src.core.platform_settings import get_setting
from src.data_models.crops_model import Crops
from src.data_models.farmer_inventory_model import FarmerInventory
from src.data_models.logistics_model import Shipments
from src.data_models.orders_model import (
    Orders, OrderStatusHistory, OrderAdjustments,
    PENDING_CONFIRMATION, CONFIRMED, PREPARING, READY_FOR_PICKUP, IN_TRANSIT, DELIVERED, COMPLETED,
    CANCELLED, DELIVERY_FAILED, DISPUTED, REFUND_PENDING, REFUNDED,
    PAYMENT_TERMS, FULL_ADVANCE, PARTIAL_ADVANCE, PAY_BEFORE_DISPATCH, PAY_ON_DELIVERY, FULFILLMENT_MODES, PICKUP, FARMER_DELIVERY, THIRD_PARTY,
)
from src.data_models.transactions_model import Transactions, Refunds, Settlements
from src.data_models.users_model import Users, VERIFIED
from src.services import inventory_core, invoices_service
from src.services.notifications_service import notify_user
from src.core.clock import utcnow

# (from, to) -> parties allowed to make the change ("system" = scheduler / internal flows)
TRANSITIONS: dict[tuple[str, str], set[str]] = {
    (PENDING_CONFIRMATION, CONFIRMED): {"system"},
    (PENDING_CONFIRMATION, CANCELLED): {"farmer", "vendor", "system", "admin"},
    (CONFIRMED, PREPARING): {"farmer"},
    (CONFIRMED, CANCELLED): {"farmer", "vendor", "admin"},
    (PREPARING, READY_FOR_PICKUP): {"farmer"},
    (PREPARING, IN_TRANSIT): {"farmer"},
    (PREPARING, CANCELLED): {"farmer", "admin"},
    (READY_FOR_PICKUP, IN_TRANSIT): {"farmer", "vendor"},
    (READY_FOR_PICKUP, DELIVERED): {"vendor", "farmer"},
    (READY_FOR_PICKUP, CANCELLED): {"farmer", "admin"},
    (IN_TRANSIT, DELIVERED): {"vendor", "farmer"},
    (IN_TRANSIT, DELIVERY_FAILED): {"farmer", "vendor"},
    (DELIVERY_FAILED, IN_TRANSIT): {"farmer"},
    (DELIVERY_FAILED, READY_FOR_PICKUP): {"farmer"},
    (DELIVERY_FAILED, CANCELLED): {"farmer", "vendor", "admin"},
    (DELIVERED, COMPLETED): {"vendor", "system", "admin"},
    (DELIVERED, DISPUTED): {"system"},
    (IN_TRANSIT, DISPUTED): {"system"},
    (DELIVERY_FAILED, DISPUTED): {"system"},
    (COMPLETED, DISPUTED): {"system"},
    (DISPUTED, COMPLETED): {"system", "admin"},
    (DISPUTED, DELIVERED): {"system", "admin"},
    (DISPUTED, REFUND_PENDING): {"system", "admin"},
    (DISPUTED, CANCELLED): {"system", "admin"},
    (CANCELLED, REFUND_PENDING): {"system"},
    (REFUND_PENDING, REFUNDED): {"system", "admin"},
}
# Stages after which the vendor can only *request* cancellation (the farmer decides).
FARMER_DECIDES_CANCEL = {PREPARING, READY_FOR_PICKUP}


def party_of(order: Orders, user_id: int | None, role: str | None = None) -> str:
    if role == "admin":
        return "admin"
    if user_id is None:
        return "system"
    if user_id == order.farmer:
        return "farmer"
    if user_id == order.vendor:
        return "vendor"
    raise HTTPException(status_code=404, detail="Order not found.")


async def lock_order(db: AsyncSession, order_id: int) -> Orders:
    order = (await db.execute(select(Orders).where(Orders.id == order_id).with_for_update())).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    return order


async def status_of(db: AsyncSession, order: Orders) -> str:
    return await misc_value(db, order.status)


# ---- money -----------------------------------------------------------------------

async def compute_breakdown(db: AsyncSession, quantity, unit_price, packaging_charge=0, transport_charge=0, discount=0) -> dict:
    quantity, unit_price = D(quantity), D(unit_price)
    subtotal = money(quantity * unit_price)
    fee_percent = D(await get_setting(db, "platform_fee_percent"))
    tax_percent = D(await get_setting(db, "tax_percent_on_fee"))
    payer = await get_setting(db, "platform_fee_payer")
    platform_fee = money(subtotal * fee_percent / 100)
    tax = money(platform_fee * tax_percent / 100)
    packaging_charge, transport_charge, discount = money(packaging_charge), money(transport_charge), money(discount)
    total = subtotal + packaging_charge + transport_charge - discount
    if payer == "vendor":
        total += platform_fee + tax
    if total < 0:
        raise HTTPException(status_code=422, detail="Discount cannot exceed the order value.")
    return {
        "subtotal": subtotal, "packaging_charge": packaging_charge, "transport_charge": transport_charge,
        "discount_amount": discount, "platform_fee": platform_fee, "tax_amount": tax, "fee_payer": payer,
        "platform_fee_percent": fee_percent, "tax_percent_on_fee": tax_percent, "total_payable": money(total),
    }


async def money_summary(db: AsyncSession, order: Orders) -> dict:
    paid_id = await misc_id(db, "payment_status", "paid")
    paid = D((await db.execute(select(func.coalesce(func.sum(Transactions.amount_paid), 0)).where(
        Transactions.order_id == order.id, Transactions.status == paid_id
    ))).scalar())
    refunded = D((await db.execute(select(func.coalesce(func.sum(Refunds.amount), 0)).where(
        Refunds.order_id == order.id, Refunds.status == "REFUNDED"
    ))).scalar())
    refund_pending = D((await db.execute(select(func.coalesce(func.sum(Refunds.amount), 0)).where(
        Refunds.order_id == order.id, Refunds.status == "REFUND_PENDING"
    ))).scalar())
    adjustments = D((await db.execute(select(func.coalesce(func.sum(OrderAdjustments.amount), 0)).where(
        OrderAdjustments.order_id == order.id
    ))).scalar())
    amount_due = money(D(order.total_price) + adjustments)
    current = await status_of(db, order)
    net_paid = paid - refunded
    outstanding = D(0) if current in (CANCELLED, REFUND_PENDING, REFUNDED) else max(amount_due - net_paid, D(0))
    advance_due = max(D(order.advance_amount or 0) - net_paid, D(0)) if order.payment_terms == PARTIAL_ADVANCE else None
    return {
        "amount_due": amount_due, "paid": money(paid), "refunded": money(refunded),
        "refund_pending": money(refund_pending), "adjustments": money(adjustments),
        "outstanding": money(outstanding), "advance_outstanding": money(advance_due) if advance_due is not None else None,
        "payment_terms": order.payment_terms,
    }


# ---- creation ---------------------------------------------------------------------

async def create_order(
    db: AsyncSession,
    *,
    listing: FarmerInventory,
    vendor_id: int,
    quantity,
    unit_price,
    source: str,
    accepted_by: int | None,
    negotiation_id: int | None = None,
    offer_id: int | None = None,
    fulfillment_mode: str | None = None,
    payment_terms: str | None = None,
    expected_delivery_date: date | None = None,
    delivery_instructions: str | None = None,
    packaging_charge=0,
    transport_charge=0,
    discount=0,
    vendor_confirmed: bool = False,
    farmer_confirmed: bool = False,
    extra_terms: dict | None = None,
) -> Orders:
    """`listing` must be locked by the caller (inventory_core.lock_listing)."""
    quantity, unit_price = D(quantity), D(unit_price)
    if listing.created_by == vendor_id:
        raise HTTPException(status_code=403, detail="You cannot buy from your own listing.")
    if not inventory_core.is_listing_live(listing):
        raise HTTPException(status_code=409, detail="This listing is not available for new orders.")
    if quantity <= 0 or unit_price <= 0:
        raise HTTPException(status_code=422, detail="Quantity and price must be positive.")
    if listing.min_order_qty and quantity < D(listing.min_order_qty) and D(listing.weight_kg) >= D(listing.min_order_qty):
        raise HTTPException(status_code=422, detail=f"Minimum order is {D(listing.min_order_qty)} {listing.unit}.")
    if quantity > D(listing.weight_kg):
        raise HTTPException(status_code=409, detail=f"Insufficient stock: only {D(listing.weight_kg)} {listing.unit} available.")

    options =[o for o in (listing.delivery_options or "pickup").split(",") if o]
    fulfillment_mode = fulfillment_mode or options[0]
    if fulfillment_mode not in FULFILLMENT_MODES:
        raise HTTPException(status_code=422, detail=f"fulfillment_mode must be one of {', '.join(FULFILLMENT_MODES)}.")
    if fulfillment_mode not in options:
        raise HTTPException(status_code=422, detail=f"This listing supports: {', '.join(options)}.")
    payment_terms = payment_terms or PAY_BEFORE_DISPATCH
    if payment_terms not in PAYMENT_TERMS:
        raise HTTPException(status_code=422, detail=f"payment_terms must be one of {', '.join(PAYMENT_TERMS)}.")

    vendor = (await db.execute(select(Users).where(Users.id == vendor_id))).scalar_one()
    farmer = (await db.execute(select(Users).where(Users.id == listing.created_by))).scalar_one()
    if payment_terms in (PAY_ON_DELIVERY,) and await get_setting(db, "pay_on_delivery_requires_verification") \
            and vendor.verification_status != VERIFIED:
        raise HTTPException(status_code=422, detail="Pay-after-delivery terms need a verified vendor account.")

    breakdown = await compute_breakdown(db, quantity, unit_price, packaging_charge, transport_charge, discount)
    threshold = D(await get_setting(db, "high_value_order_threshold"))
    if threshold > 0 and breakdown["total_payable"] >= threshold and \
            (vendor.verification_status != VERIFIED or farmer.verification_status != VERIFIED):
        raise HTTPException(
            status_code=422,
            detail=f"Orders of ₹{threshold} or more need both parties to be verified.",
        )

    advance = D(0)
    if payment_terms == FULL_ADVANCE:
        advance = breakdown["total_payable"]
    elif payment_terms == PARTIAL_ADVANCE:
        advance = money(breakdown["total_payable"] * D(await get_setting(db, "partial_advance_percent")) / 100)

    crop = (await db.execute(select(Crops).where(Crops.id == listing.crop))).scalar_one_or_none()
    now = utcnow()
    both_confirmed = vendor_confirmed and farmer_confirmed
    confirmation_hours = int(await get_setting(db, "order_confirmation_hours"))
    order = Orders(
        farmer_inventory=listing.id, vendor=vendor_id, farmer=listing.created_by,
        quantity_kg=quantity, unit=listing.unit, unit_price=unit_price,
        subtotal=breakdown["subtotal"], packaging_charge=breakdown["packaging_charge"],
        transport_charge=breakdown["transport_charge"], discount_amount=breakdown["discount_amount"],
        platform_fee=breakdown["platform_fee"], tax_amount=breakdown["tax_amount"],
        total_price=breakdown["total_payable"], payment_terms=payment_terms, advance_amount=advance,
        fulfillment_mode=fulfillment_mode, delivery_instructions=delivery_instructions,
        expected_delivery_date=expected_delivery_date, negotiation_id=negotiation_id, offer_id=offer_id,
        source=source, agreed_at=now,
        vendor_confirmed_at=now if vendor_confirmed else None,
        farmer_confirmed_at=now if farmer_confirmed else None,
        confirmation_deadline=None if both_confirmed else now + timedelta(hours=confirmation_hours),
        status=await misc_id(db, "order_status", CONFIRMED if both_confirmed else PENDING_CONFIRMATION),
        created_at=now, updated_at=now,
    )
    db.add(order)
    await db.flush()
    order.order_number = f"ORD-{now:%Y%m%d}-{order.id:06d}"
    order.terms_snapshot = {
        "order_number": order.order_number,
        "agreed_at": now.isoformat(),
        "accepted_by": accepted_by,
        "source": source,
        "negotiation_id": negotiation_id,
        "offer_id": offer_id,
        "buyer_id": vendor_id,
        "seller_id": listing.created_by,
        "listing_id": listing.id,
        "produce": {
            "crop_id": listing.crop, "display_name": " ".join(x for x in (crop.crop_name if crop else None, listing.variety) if x),
            "variety": listing.variety, "quality_grade": listing.quality_grade, "harvest_date": str(listing.harvest_date) if listing.harvest_date else None,
            "packaging": listing.packaging, "batch_code": listing.batch_code,
        },
        "quantity": str(quantity), "unit": listing.unit, "unit_price": str(unit_price),
        **{k: str(v) if isinstance(v, Decimal) else v for k, v in breakdown.items()},
        "payment_terms": payment_terms, "advance_amount": str(advance),
        "fulfillment_mode": fulfillment_mode, "expected_delivery_date": str(expected_delivery_date) if expected_delivery_date else None,
        "delivery_instructions": delivery_instructions,
        **(extra_terms or {}),
    }

    await inventory_core.reserve(
        db, listing, quantity, order.id, accepted_by,
        expires_at=None if both_confirmed else order.confirmation_deadline,
    )
    db.add(Shipments(order_id=order.id, mode=fulfillment_mode, status="planned", reschedule_count=0,
                     created_at=now, updated_at=now))
    db.add(OrderStatusHistory(order_id=order.id, from_status=None,
                              to_status=CONFIRMED if both_confirmed else PENDING_CONFIRMATION,
                              actor_id=accepted_by, note=f"created from {source}", created_at=now))
    if both_confirmed:
        await invoices_service.issue(db, order, "order_receipt")
    audit(db, "order.created", "order", order.id, actor_id=accepted_by, after=order.terms_snapshot)

    params = {"order_number": order.order_number, "crop": crop.crop_name if crop else "", "quantity": quantity,
              "unit": listing.unit, "price": unit_price}
    for party_id, confirmed in ((order.farmer, farmer_confirmed), (order.vendor, vendor_confirmed)):
        if party_id == accepted_by:
            continue
        template = "order_confirmed" if both_confirmed else ("order_created" if not confirmed else "order_status")
        await notify_user(db, party_id, template, {**params, "status": PENDING_CONFIRMATION},
                          ref_type="order", ref_id=order.id)
    return order


# ---- lifecycle ----------------------------------------------------------------------

async def _check_payment_gate(db: AsyncSession, order: Orders, to_status: str):
    summary = await money_summary(db, order)
    paid = summary["paid"] - summary["refunded"]
    total = summary["amount_due"]
    terms = order.payment_terms
    if to_status == PREPARING:
        if terms == FULL_ADVANCE and paid < total:
            raise HTTPException(status_code=409, detail="Full advance payment is required before preparation.")
        if terms == PARTIAL_ADVANCE and paid < D(order.advance_amount or 0):
            raise HTTPException(status_code=409, detail="The advance payment is required before preparation.")
    if to_status in (READY_FOR_PICKUP, IN_TRANSIT) and terms in (FULL_ADVANCE, PAY_BEFORE_DISPATCH) and paid < total:
        raise HTTPException(status_code=409, detail="Full payment is required before dispatch.")
    if to_status == COMPLETED and paid < total:
        raise HTTPException(status_code=409, detail=f"₹{money(total - paid)} is still outstanding.")


def _check_mode(order: Orders, to_status: str):
    if to_status == READY_FOR_PICKUP and order.fulfillment_mode in (FARMER_DELIVERY, THIRD_PARTY):
        raise HTTPException(status_code=409, detail="This order is delivered by the farmer/transporter; mark it in transit.")
    if to_status == IN_TRANSIT and order.fulfillment_mode == PICKUP:
        raise HTTPException(status_code=409, detail="Pickup orders go from ready-for-pickup straight to delivered.")


async def transition(
    db: AsyncSession, order: Orders, to_status: str, actor_id: int | None, actor_role: str | None = None,
    note: str | None = None, skip_payment_gate: bool = False,
) -> str:
    """Move a (locked) order to `to_status` if the actor may. Returns the previous status."""
    current = await status_of(db, order)
    allowed = TRANSITIONS.get((current, to_status))
    if not allowed:
        raise HTTPException(status_code=409, detail=f"Order can't move from '{current}' to '{to_status}'.")
    party = party_of(order, actor_id, actor_role)
    if party not in allowed:
        raise HTTPException(status_code=403, detail=f"Only {' or '.join(sorted(allowed - {'system'})) or 'the system'} can mark this order '{to_status}'.")
    _check_mode(order, to_status)
    if not skip_payment_gate:
        await _check_payment_gate(db, order, to_status)

    now = utcnow()
    order.status = await misc_id(db, "order_status", to_status)
    order.updated_at = now
    db.add(OrderStatusHistory(order_id=order.id, from_status=current, to_status=to_status,
                              actor_id=actor_id, note=(note or "")[:255] or None, created_at=now))

    if to_status == CANCELLED:
        order.cancelled_at = now
        order.cancelled_by = actor_id
        order.cancel_reason = (note or "cancelled")[:255]
        await inventory_core.release(db, order.id, actor_id, f"order cancelled: {order.cancel_reason}")
    elif to_status == DELIVERED:
        order.delivered_at = order.delivered_at or now
        await inventory_core.consume(db, order.id, actor_id)
    elif to_status == COMPLETED:
        order.completed_at = now
        await inventory_core.consume(db, order.id, actor_id)
        await _create_settlement(db, order)
        await invoices_service.issue(db, order, "invoice")
    elif to_status == CONFIRMED:
        await inventory_core.hold_until_fulfilment(db, order.id)
        await invoices_service.issue(db, order, "order_receipt")

    audit(db, f"order.{to_status}", "order", order.id, actor_id=actor_id, actor_role=party,
          before={"status": current}, after={"status": to_status, "note": note})

    crop = (order.terms_snapshot or {}).get("produce", {}).get("display_name", "")
    template = {CANCELLED: "order_cancelled", COMPLETED: "order_completed", DELIVERED: "order_delivered",
                READY_FOR_PICKUP: "order_ready", CONFIRMED: "order_confirmed"}.get(to_status, "order_status")
    params = {"order_number": order.order_number, "status": to_status, "reason": note or "", "crop": crop}
    for party_id in (order.farmer, order.vendor):
        if party_id != actor_id:
            await notify_user(db, party_id, template, params, ref_type="order", ref_id=order.id)
    return current


async def confirm(db: AsyncSession, order: Orders, actor_id: int) -> dict:
    """Each party confirms the terms (incl. charges). When both have, the order is CONFIRMED."""
    if await status_of(db, order) != PENDING_CONFIRMATION:
        raise HTTPException(status_code=409, detail="This order is not awaiting confirmation.")
    party = party_of(order, actor_id)
    now = utcnow()
    if party == "farmer":
        order.farmer_confirmed_at = order.farmer_confirmed_at or now
    else:
        order.vendor_confirmed_at = order.vendor_confirmed_at or now
    audit(db, "order.party_confirmed", "order", order.id, actor_id=actor_id, actor_role=party)
    if order.farmer_confirmed_at and order.vendor_confirmed_at:
        order.confirmation_deadline = None
        await transition(db, order, CONFIRMED, None, note="confirmed by both parties")
        return {"status": CONFIRMED}
    return {"status": PENDING_CONFIRMATION, "waiting_for": "vendor" if party == "farmer" else "farmer"}


async def cancel(db: AsyncSession, order: Orders, actor_id: int, actor_role: str | None, reason: str) -> dict:
    """Apply the cancellation policy: direct cancel, or a request the farmer must approve."""
    current = await status_of(db, order)
    party = party_of(order, actor_id, actor_role)
    if current in FARMER_DECIDES_CANCEL and party == "vendor":
        order.cancel_requested_by = actor_id
        order.cancel_request_reason = reason[:255]
        order.cancel_requested_at = utcnow()
        await notify_user(db, order.farmer, "order_cancel_requested",
                          {"order_number": order.order_number, "reason": reason, "party": "The vendor"},
                          ref_type="order", ref_id=order.id)
        audit(db, "order.cancel_requested", "order", order.id, actor_id=actor_id, actor_role=party, after={"reason": reason})
        return {"status": current, "cancellation": "requested", "message": "The farmer must approve this cancellation."}
    if current in (IN_TRANSIT, DELIVERED, COMPLETED) and party != "admin":
        raise HTTPException(status_code=409, detail="This order can no longer be cancelled. Raise a dispute instead.")
    await transition(db, order, CANCELLED, actor_id, actor_role, note=reason)
    await refund_if_paid(db, order, actor_id, f"order cancelled: {reason}")
    return {"status": await status_of(db, order), "cancellation": "done"}


async def refund_if_paid(db: AsyncSession, order: Orders, actor_id: int | None, reason: str, amount=None, dispute_id=None):
    """Create a pending refund for money already collected; the payments service processes it."""
    summary = await money_summary(db, order)
    refundable = summary["paid"] - summary["refunded"] - summary["refund_pending"]
    amount = money(amount) if amount is not None else refundable
    if amount <= 0:
        return None
    if amount > refundable:
        raise HTTPException(status_code=422, detail=f"Refund exceeds the refundable amount (₹{refundable}).")
    paid_id = await misc_id(db, "payment_status", "paid")
    txn = (await db.execute(select(Transactions).where(
        Transactions.order_id == order.id, Transactions.status == paid_id
    ).order_by(Transactions.amount_paid.desc()))).scalars().first()
    refund = Refunds(order_id=order.id, transaction_id=txn.id if txn else None, dispute_id=dispute_id, amount=amount,
                     reason=reason[:255], status="REFUND_PENDING", initiated_by=actor_id, created_at=utcnow())
    db.add(refund)
    current = await status_of(db, order)
    if (current, REFUND_PENDING) in TRANSITIONS:
        await transition(db, order, REFUND_PENDING, None, note=reason, skip_payment_gate=True)
    for party_id in (order.vendor, order.farmer):
        await notify_user(db, party_id, "refund_status",
                          {"order_number": order.order_number, "amount": amount, "status": "pending"},
                          ref_type="order", ref_id=order.id)
    return refund


async def _create_settlement(db: AsyncSession, order: Orders):
    exists = (await db.execute(select(Settlements.id).where(Settlements.order_id == order.id))).first()
    if exists:
        return
    summary = await money_summary(db, order)
    payer = (order.terms_snapshot or {}).get("fee_payer", "vendor")
    gross = money(D(order.subtotal) + D(order.packaging_charge) + D(order.transport_charge) - D(order.discount_amount))
    fee = money(D(order.platform_fee) + D(order.tax_amount)) if payer == "farmer" else D(0)
    cash_collected = D((await db.execute(select(func.coalesce(func.sum(Transactions.amount_paid), 0)).where(
        Transactions.order_id == order.id, Transactions.payment_method == "cash",
        Transactions.status == await misc_id(db, "payment_status", "paid"),
    ))).scalar())
    net = money(gross - fee + summary["adjustments"] - summary["refunded"] - cash_collected)
    db.add(Settlements(
        order_id=order.id, farmer=order.farmer, gross_amount=gross, fee_deducted=fee,
        adjustments=summary["adjustments"] - summary["refunded"], collected_directly=cash_collected,
        net_amount=net, status="pending" if net > 0 else "paid", created_at=utcnow(),
    ))
