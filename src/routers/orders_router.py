from datetime import date
from typing import Optional, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.idempotency import run_idempotent
from src.data_models.users_model import Users
from src.db_connections.database import get_db_async
from src.schemas.logistics_schema import (
    ShipmentPlanSchema, DispatchSchema, DeliveryConfirmSchema, DeliveryFailureSchema, RescheduleSchema,
)
from src.schemas.orders_schema import (
    DirectOrderSchema, StatusChangeSchema, CancelSchema, ReorderSchema, PostOrderSchema, UpdateOrderStatus,
)
from src.security_utils.role_guard import require_roles, current_user_with_role, FARMER, VENDOR
from src.services.invoices_service import InvoicesService
from src.services.logistics_service import LogisticsService
from src.services.orders_service import OrdersService

router = APIRouter(prefix="/api", tags=["Orders"])

parties = require_roles(FARMER, VENDOR)


def orders_service() -> OrdersService:
    return OrdersService()


def logistics_service() -> LogisticsService:
    return LogisticsService()


# ---- orders ------------------------------------------------------------------------

@router.post("/orders/direct")
async def direct_order(
    payload: DirectOrderSchema,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db_async),
    service: OrdersService = Depends(orders_service),
    user: Users = Depends(require_roles(VENDOR)),
):
    """Order at the asking (or quantity-tier) price. Stock is reserved; the farmer confirms."""
    return await run_idempotent(db, idempotency_key, user.id, "orders-direct", payload.model_dump(),
                                lambda: service.direct_order(user, payload, db))


@router.get("/orders")
async def list_orders(
    role: Optional[Literal["farmer", "vendor"]] = None,
    status: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    counterparty_id: Optional[int] = None,
    crop_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_async),
    service: OrdersService = Depends(orders_service),
    user: Users = Depends(parties),
):
    return await service.list_orders(user, db, role, status, date_from, date_to, counterparty_id, crop_id, page, page_size)


@router.get("/orders/{order_id}")
async def order_detail(
    order_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: OrdersService = Depends(orders_service),
    user: Users = Depends(current_user_with_role),
):
    """Agreed terms snapshot, price breakdown, payments, status timeline, shipment and invoices."""
    return await service.detail(user, order_id, db, is_admin=user.role_name == "admin")


@router.post("/orders/{order_id}/confirm")
async def confirm_order(
    order_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: OrdersService = Depends(orders_service),
    user: Users = Depends(parties),
):
    return await service.confirm(user, order_id, db)


@router.post("/orders/{order_id}/status")
async def change_order_status(
    order_id: int,
    payload: StatusChangeSchema,
    db: AsyncSession = Depends(get_db_async),
    service: OrdersService = Depends(orders_service),
    user: Users = Depends(parties),
):
    return await service.change_status(user, order_id, payload.status, payload.note, db)


@router.post("/orders/{order_id}/cancel")
async def cancel_order(
    order_id: int,
    payload: CancelSchema,
    db: AsyncSession = Depends(get_db_async),
    service: OrdersService = Depends(orders_service),
    user: Users = Depends(parties),
):
    """Cancel per policy. Once preparation starts, a vendor's cancellation becomes a request the farmer decides."""
    return await service.cancel(user, order_id, payload.reason, db)


@router.post("/orders/{order_id}/cancel-request/{decision}")
async def decide_cancel_request(
    order_id: int,
    decision: Literal["approve", "decline"],
    db: AsyncSession = Depends(get_db_async),
    service: OrdersService = Depends(orders_service),
    user: Users = Depends(require_roles(FARMER)),
):
    return await service.decide_cancel_request(user, order_id, decision == "approve", db)


@router.post("/orders/{order_id}/reorder")
async def reorder(
    order_id: int,
    payload: ReorderSchema,
    db: AsyncSession = Depends(get_db_async),
    service: OrdersService = Depends(orders_service),
    user: Users = Depends(require_roles(VENDOR)),
):
    return await service.reorder(user, order_id, payload, db)


# ---- shipment / delivery ---------------------------------------------------------------

@router.get("/orders/{order_id}/shipment")
async def get_shipment(
    order_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: LogisticsService = Depends(logistics_service),
    user: Users = Depends(parties),
):
    return await service.get(user, order_id, db)


@router.put("/orders/{order_id}/shipment")
async def update_shipment(
    order_id: int,
    payload: ShipmentPlanSchema,
    db: AsyncSession = Depends(get_db_async),
    service: LogisticsService = Depends(logistics_service),
    user: Users = Depends(parties),
):
    return await service.update_plan(user, order_id, payload, db)


@router.post("/orders/{order_id}/dispatch")
async def dispatch_order(
    order_id: int,
    payload: DispatchSchema,
    db: AsyncSession = Depends(get_db_async),
    service: LogisticsService = Depends(logistics_service),
    user: Users = Depends(parties),
):
    return await service.dispatch(user, order_id, payload, db)


@router.post("/orders/{order_id}/delivery/confirm")
async def confirm_delivery(
    order_id: int,
    payload: DeliveryConfirmSchema,
    db: AsyncSession = Depends(get_db_async),
    service: LogisticsService = Depends(logistics_service),
    user: Users = Depends(parties),
):
    """Proof of delivery: vendor confirms receipt, or the farmer enters the vendor's delivery code."""
    return await service.confirm_delivery(user, order_id, payload, db)


@router.post("/orders/{order_id}/delivery/failed")
async def delivery_failed(
    order_id: int,
    payload: DeliveryFailureSchema,
    db: AsyncSession = Depends(get_db_async),
    service: LogisticsService = Depends(logistics_service),
    user: Users = Depends(parties),
):
    return await service.report_failure(user, order_id, payload, db)


@router.post("/orders/{order_id}/delivery/reschedule")
async def reschedule_delivery(
    order_id: int,
    payload: RescheduleSchema,
    db: AsyncSession = Depends(get_db_async),
    service: LogisticsService = Depends(logistics_service),
    user: Users = Depends(require_roles(FARMER)),
):
    return await service.reschedule(user, order_id, payload, db)


# ---- invoices ------------------------------------------------------------------------------

@router.get("/orders/{order_id}/invoices")
async def order_invoices(
    order_id: int,
    db: AsyncSession = Depends(get_db_async),
    user: Users = Depends(current_user_with_role),
):
    return await InvoicesService().list_for_order(order_id, user.id, user.role_name == "admin", db)


@router.get("/invoices/{invoice_id}/download")
async def download_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db_async),
    user: Users = Depends(current_user_with_role),
):
    return await InvoicesService().download(invoice_id, user.id, user.role_name == "admin", db)


# ---- legacy endpoints ------------------------------------------------------------------------

@router.post("/order/", deprecated=True)
async def legacy_post_order(
    payload: PostOrderSchema,
    db: AsyncSession = Depends(get_db_async),
    service: OrdersService = Depends(orders_service),
    user: Users = Depends(require_roles(VENDOR)),
):
    """Deprecated: use POST /api/orders/direct."""
    if not payload.stock_id or not payload.quantity:
        raise HTTPException(status_code=422, detail="stock_id and quantity are required.")
    return await service.direct_order(user, DirectOrderSchema(listing_id=payload.stock_id, quantity=payload.quantity), db)


@router.get("/vendor/orders/", deprecated=True)
async def legacy_vendor_orders(
    id: int,
    db: AsyncSession = Depends(get_db_async),
    service: OrdersService = Depends(orders_service),
    user: Users = Depends(parties),
):
    if user.id != id:
        raise HTTPException(status_code=403, detail="You can only view your own orders.")
    return (await service.list_orders(user, db, role="vendor", page_size=100))["data"]


@router.get("/farmer/orders/", deprecated=True)
async def legacy_farmer_orders(
    id: int,
    db: AsyncSession = Depends(get_db_async),
    service: OrdersService = Depends(orders_service),
    user: Users = Depends(parties),
):
    if user.id != id:
        raise HTTPException(status_code=403, detail="You can only view your own orders.")
    return (await service.list_orders(user, db, role="farmer", page_size=100))["data"]


@router.put("/order-status/", deprecated=True)
async def legacy_order_status(
    payload: UpdateOrderStatus,
    db: AsyncSession = Depends(get_db_async),
    service: OrdersService = Depends(orders_service),
    user: Users = Depends(parties),
):
    """Deprecated: use /api/orders/{id}/confirm, /status or /cancel."""
    if not payload.order_id or not payload.status:
        raise HTTPException(status_code=422, detail="order_id and status are required.")
    return await service.legacy_status(user, payload, db)
