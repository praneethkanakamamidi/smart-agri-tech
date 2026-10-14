"""
Order and logistics tools. Status moves go through order_core's state machine. There is
deliberately no tool to mark an order delivered or completed: that needs the vendor's delivery
code or the vendor's own action through the regular API.
"""
from datetime import date, datetime

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.context import RunContext
from src.agents.integrations.maps import GeoPoint, get_maps
from src.agents.retrieval import geo
from src.agents.tools.base import tool
from src.core.money import D
from src.data_models.farmer_inventory_model import FarmerInventory
from src.data_models.logistics_model import Shipments
from src.data_models.orders_model import Orders, OrderStatusHistory, PENDING_CONFIRMATION
from src.data_models.profiles_model import FarmerProfiles, VendorProfiles
from src.data_models.users_model import Users
from src.schemas.logistics_schema import ShipmentPlanSchema
from src.security_utils.role_guard import ADMIN
from src.services import order_core
from src.services.logistics_service import LogisticsService
from src.services.orders_service import OrdersService


class OrderRef(BaseModel):
    order_id: int = Field(..., gt=0)


async def _order_for(db: AsyncSession, actor: Users, order_id: int) -> Orders:
    order = (await db.execute(select(Orders).where(Orders.id == order_id))).scalar_one_or_none()
    if not order or (actor.role_name != ADMIN and actor.id not in (order.farmer, order.vendor)):
        raise HTTPException(status_code=404, detail="Order not found.")
    return order


@tool("get_order_status", OrderRef, "Order status, agreed terms, payments, shipment and timeline (parties and admins).")
async def get_order_status(db: AsyncSession, actor: Users, args: OrderRef, ctx: RunContext) -> dict:
    order = await _order_for(db, actor, args.order_id)
    status = await order_core.status_of(db, order)
    shipment = (await db.execute(select(Shipments).where(Shipments.order_id == order.id))).scalar_one_or_none()
    history = (await db.execute(select(OrderStatusHistory).where(OrderStatusHistory.order_id == order.id)
                                .order_by(OrderStatusHistory.id))).scalars().all()
    is_farmer = actor.id == order.farmer
    awaiting_me = status == PENDING_CONFIRMATION and (
        (is_farmer and not order.farmer_confirmed_at) or (actor.id == order.vendor and not order.vendor_confirmed_at))
    snapshot = order.terms_snapshot or {}
    return {
        "order_id": order.id, "order_number": order.order_number, "status": status,
        "my_role": "farmer" if is_farmer else "vendor" if actor.id == order.vendor else "admin",
        "produce": (snapshot.get("produce") or {}).get("display_name"),
        "quantity": str(D(order.quantity_kg)), "unit": order.unit, "unit_price": str(D(order.unit_price)),
        "total_payable": str(D(order.total_price)), "payment_terms": order.payment_terms,
        "fulfillment_mode": order.fulfillment_mode, "expected_delivery_date": order.expected_delivery_date,
        "awaiting_my_confirmation": awaiting_me,
        "payments": await order_core.money_summary(db, order),
        "shipment": LogisticsService._view(shipment) if shipment else None,
        "timeline": [{"from": h.from_status, "to": h.to_status, "at": h.created_at, "note": h.note} for h in history],
    }


@tool("confirm_order", OrderRef, "Record this party's confirmation of the order terms. Needs approval.")
async def confirm_order(db: AsyncSession, actor: Users, args: OrderRef, ctx: RunContext) -> dict:
    return await OrdersService().confirm(actor, args.order_id, db)


class SchedulePickupInput(BaseModel):
    order_id: int = Field(..., gt=0)
    pickup_date: date
    window_start: datetime | None = None
    window_end: datetime | None = None
    pickup_address: str | None = Field(None, max_length=255)
    pickup_instructions: str | None = Field(None, max_length=1000)
    delivery_address: str | None = Field(None, max_length=255)

    @model_validator(mode="after")
    def sane_dates(self):
        if self.pickup_date < date.today():
            raise ValueError("pickup_date can't be in the past")
        if self.window_start and self.window_end and self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start")
        return self


@tool("schedule_pickup", SchedulePickupInput, "Set the pickup/delivery date and window on the shipment plan. Needs approval.")
async def schedule_pickup(db: AsyncSession, actor: Users, args: SchedulePickupInput, ctx: RunContext) -> dict:
    plan = ShipmentPlanSchema(**args.model_dump(exclude={"order_id"}, exclude_none=True))
    shipment = await LogisticsService().update_plan(actor, args.order_id, plan, db)
    return {"order_id": args.order_id, "shipment": shipment,
            "note": "Pickup date recorded on the order and the other party was notified. No transport was booked."}


async def _points(db: AsyncSession, order: Orders) -> tuple[GeoPoint | None, GeoPoint | None]:
    listing = await db.get(FarmerInventory, order.farmer_inventory)
    farm = (await db.execute(select(FarmerProfiles.latitude, FarmerProfiles.longitude)
                             .where(FarmerProfiles.user_id == order.farmer))).first()
    vendor = (await db.execute(select(VendorProfiles.latitude, VendorProfiles.longitude)
                               .where(VendorProfiles.user_id == order.vendor))).first()
    origin = None
    if listing and geo.valid_coordinates(listing.pickup_latitude, listing.pickup_longitude):
        origin = GeoPoint(float(listing.pickup_latitude), float(listing.pickup_longitude))
    elif farm and geo.valid_coordinates(farm[0], farm[1]):
        origin = GeoPoint(float(farm[0]), float(farm[1]))
    destination = GeoPoint(float(vendor[0]), float(vendor[1])) if vendor and geo.valid_coordinates(vendor[0], vendor[1]) else None
    return origin, destination


@tool("get_delivery_options", OrderRef, "Fulfilment options on the listing with travel estimates (not bookings).")
async def get_delivery_options(db: AsyncSession, actor: Users, args: OrderRef, ctx: RunContext) -> dict:
    order = await _order_for(db, actor, args.order_id)
    listing = await db.get(FarmerInventory, order.farmer_inventory)
    options = [o for o in ((listing.delivery_options if listing else None) or "pickup").split(",") if o]
    origin, destination = await _points(db, order)
    route = await get_maps().route(origin, destination) if origin and destination else None
    who = {"pickup": "vendor collects at the farm", "farmer_delivery": "farmer delivers",
           "vendor_transport": "vendor arranges transport", "third_party": "third-party transporter"}
    return {
        "order_id": order.id, "current_mode": order.fulfillment_mode,
        "options": [{"mode": o, "description": who.get(o, o)} for o in options],
        "route_estimate": route.as_dict() if route else None,
        "note": ("Travel figures are estimates for planning. Nothing has been booked." if route else
                 "Add farm and business coordinates to both profiles to get travel estimates."),
    }
