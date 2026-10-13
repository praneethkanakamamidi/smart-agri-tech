from typing import Optional

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.idempotency import run_idempotent
from src.data_models.users_model import Users
from src.db_connections.database import get_db_async
from src.schemas.payment_schema import CreatePayment, VerifyPayment, RecordManualPayment
from src.security_utils.role_guard import require_roles, current_user_with_role, FARMER, VENDOR
from src.services.payment_service import PaymentsService

router = APIRouter(prefix="/api", tags=["Payments"])


def payment_service() -> PaymentsService:
    return PaymentsService()


@router.post("/order/payment")
async def create_payment(
    payload: CreatePayment,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db_async),
    service: PaymentsService = Depends(payment_service),
    user: Users = Depends(require_roles(VENDOR)),
):
    """Start a gateway payment. The amount (full, advance or balance) is calculated on the server."""
    return await run_idempotent(db, idempotency_key, user.id, f"payment-create:{payload.order_id}",
                                payload.model_dump(), lambda: service.create_payment_order(payload, user.id, db))


@router.post("/order/verify-payment")
async def verify_payment(
    payload: VerifyPayment,
    db: AsyncSession = Depends(get_db_async),
    service: PaymentsService = Depends(payment_service),
    user: Users = Depends(require_roles(VENDOR)),
):
    """Server-side signature check after checkout. The webhook confirms the same payment independently."""
    return await service.verify_payment(payload, user.id, db)


@router.post("/payments/webhook/razorpay", include_in_schema=False)
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db_async),
    service: PaymentsService = Depends(payment_service),
):
    return await service.handle_webhook(await request.body(), x_razorpay_signature, db)


@router.get("/orders/{order_id}/payments")
async def payment_summary(
    order_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: PaymentsService = Depends(payment_service),
    user: Users = Depends(current_user_with_role),
):
    """Amount due, paid, refunded and outstanding, with the price breakdown and every payment attempt."""
    return await service.summary(user.id, order_id, db, is_admin=user.role_name == "admin")


@router.post("/orders/{order_id}/payments/manual")
async def record_manual_payment(
    order_id: int,
    payload: RecordManualPayment,
    db: AsyncSession = Depends(get_db_async),
    service: PaymentsService = Depends(payment_service),
    user: Users = Depends(require_roles(FARMER)),
):
    """Farmer records cash/UPI/bank transfer received directly. The vendor is notified and can dispute it."""
    return await service.record_manual_payment(user.id, order_id, payload, db)


@router.get("/settlements")
async def my_settlements(
    db: AsyncSession = Depends(get_db_async),
    service: PaymentsService = Depends(payment_service),
    user: Users = Depends(require_roles(FARMER)),
):
    """Farmer payouts: pending and paid settlements for completed orders."""
    return await service.farmer_settlements(user.id, db)
