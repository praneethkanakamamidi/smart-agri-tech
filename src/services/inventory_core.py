"""
Stock accounting for listings. All changes go through these functions so that:
- the listing row is locked (SELECT ... FOR UPDATE) - concurrent acceptances can't oversell;
- available/reserved/sold never go negative;
- every change is written to the inventory_movements ledger.
Callers commit.
"""
from datetime import datetime, date
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.money import D
from src.data_models.farmer_inventory_model import (
    FarmerInventory, ACTIVE, RESERVED, SOLD, PAUSED, EXPIRED, DRAFT,
)
from src.data_models.listing_extras_model import InventoryReservations, InventoryMovements
from src.data_models.crops_model import Crops
from src.services.notifications_service import notify_user
from src.core.clock import utcnow

SELLABLE_STATUSES = (ACTIVE,)


async def lock_listing(db: AsyncSession, listing_id: int) -> FarmerInventory:
    listing = (await db.execute(
        select(FarmerInventory).where(FarmerInventory.id == listing_id).with_for_update()
    )).scalar_one_or_none()
    if not listing or listing.deleted_at:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found.")
    return listing


def _ledger(db, listing: FarmerInventory, movement_type: str, quantity: Decimal, actor_id, ref_type=None, ref_id=None, note=None):
    db.add(InventoryMovements(
        listing_id=listing.id, movement_type=movement_type, quantity=quantity,
        available_after=listing.weight_kg, reserved_after=listing.reserved_qty, sold_after=listing.sold_qty,
        ref_type=ref_type, ref_id=ref_id, actor_id=actor_id, note=note, created_at=utcnow(),
    ))


def refresh_status(listing: FarmerInventory):
    """Derive reserved/sold/active from quantities (never overrides draft/paused/expired/removed)."""
    if listing.status not in (ACTIVE, RESERVED, SOLD):
        return
    available, reserved = D(listing.weight_kg), D(listing.reserved_qty)
    if available > 0:
        listing.status = ACTIVE
    elif reserved > 0:
        listing.status = RESERVED
    else:
        listing.status = SOLD


def is_listing_live(listing: FarmerInventory) -> bool:
    return (
        listing.status == ACTIVE
        and listing.deleted_at is None
        and D(listing.weight_kg) > 0
        and (listing.available_until is None or listing.available_until >= date.today())
    )


async def _maybe_low_stock_alert(db: AsyncSession, listing: FarmerInventory):
    threshold = listing.low_stock_threshold
    if threshold is None or D(listing.weight_kg) > D(threshold):
        return
    crop = (await db.execute(select(Crops.crop_name).where(Crops.id == listing.crop))).scalar_one_or_none()
    await notify_user(
        db, listing.created_by, "low_stock",
        {"crop": crop, "quantity": D(listing.weight_kg), "unit": listing.unit},
        ref_type="listing", ref_id=listing.id,
        dedupe_key=f"low_stock:{listing.id}:{date.today().isoformat()}",
    )


async def reserve(
    db: AsyncSession, listing: FarmerInventory, quantity, order_id: int, actor_id: int | None,
    expires_at: datetime | None,
) -> InventoryReservations:
    """Move `quantity` from available to reserved for an order. `listing` must be locked."""
    quantity = D(quantity)
    if quantity <= 0:
        raise HTTPException(status_code=422, detail="Quantity must be positive.")
    if D(listing.weight_kg) < quantity:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Insufficient stock: only {D(listing.weight_kg)} {listing.unit} available.",
        )
    listing.weight_kg = D(listing.weight_kg) - quantity
    listing.reserved_qty = D(listing.reserved_qty) + quantity
    refresh_status(listing)
    reservation = InventoryReservations(
        listing_id=listing.id, order_id=order_id, quantity=quantity, status="active",
        expires_at=expires_at, created_at=utcnow(),
    )
    db.add(reservation)
    _ledger(db, listing, "reserve", -quantity, actor_id, "order", order_id)
    await _maybe_low_stock_alert(db, listing)
    return reservation


async def _active_reservation(db: AsyncSession, order_id: int) -> InventoryReservations | None:
    return (await db.execute(
        select(InventoryReservations)
        .where(InventoryReservations.order_id == order_id, InventoryReservations.status == "active")
        .with_for_update()
    )).scalar_one_or_none()


async def release(db: AsyncSession, order_id: int, actor_id: int | None, reason: str, expired: bool = False):
    """Return an order's reserved stock to available (cancellation, expiry, failed confirmation)."""
    reservation = await _active_reservation(db, order_id)
    if not reservation:
        return
    listing = await lock_listing(db, reservation.listing_id)
    listing.reserved_qty = max(D(listing.reserved_qty) - D(reservation.quantity), D(0))
    listing.weight_kg = D(listing.weight_kg) + D(reservation.quantity)
    refresh_status(listing)
    reservation.status = "expired" if expired else "released"
    reservation.released_at = utcnow()
    reservation.reason = reason[:120]
    _ledger(db, listing, "release", D(reservation.quantity), actor_id, "order", order_id, reason[:255])


async def hold_until_fulfilment(db: AsyncSession, order_id: int):
    """Once both parties confirm, the reservation no longer times out."""
    reservation = await _active_reservation(db, order_id)
    if reservation:
        reservation.expires_at = None


async def consume(db: AsyncSession, order_id: int, actor_id: int | None):
    """Reserved stock becomes sold when the order is delivered."""
    reservation = await _active_reservation(db, order_id)
    if not reservation:
        return
    listing = await lock_listing(db, reservation.listing_id)
    listing.reserved_qty = max(D(listing.reserved_qty) - D(reservation.quantity), D(0))
    listing.sold_qty = D(listing.sold_qty) + D(reservation.quantity)
    refresh_status(listing)
    reservation.status = "consumed"
    reservation.released_at = utcnow()
    _ledger(db, listing, "sell", D(reservation.quantity), actor_id, "order", order_id)


async def set_available(db: AsyncSession, listing: FarmerInventory, new_available, actor_id: int, note: str = "stock update"):
    """Farmer sets the saleable quantity directly. `listing` must be locked."""
    new_available = D(new_available)
    if new_available < 0:
        raise HTTPException(status_code=422, detail="Available quantity cannot be negative.")
    delta = new_available - D(listing.weight_kg)
    if delta == 0:
        return
    listing.weight_kg = new_available
    if listing.status in (SOLD, RESERVED) and new_available > 0:
        listing.status = ACTIVE
    refresh_status(listing)
    _ledger(db, listing, "add" if delta > 0 else "adjust", delta, actor_id, note=note)
    await _maybe_low_stock_alert(db, listing)


def initial_ledger(db: AsyncSession, listing: FarmerInventory, actor_id: int):
    _ledger(db, listing, "add", D(listing.weight_kg), actor_id, note="listing created")


__all__ = [
    "lock_listing", "reserve", "release", "consume", "set_available", "hold_until_fulfilment",
    "refresh_status", "is_listing_live", "initial_ledger", "SELLABLE_STATUSES", "PAUSED", "EXPIRED", "DRAFT",
]
