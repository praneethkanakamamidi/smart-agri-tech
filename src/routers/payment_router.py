from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.payment_service import PaymentsService
from src.db_connections.database import get_db_async
from src.services.login_service import LoginService
from src.data_models.users_model import Users
from src.schemas.payment_schema import CreatePayment, VerifyPayment

router = APIRouter(prefix="/api", tags=["Payments"])

get_current_active_user = LoginService.get_current_active_user


def payment_service() -> PaymentsService:
    return PaymentsService()


@router.post("/order/payment")
async def create_payment(
    payload: CreatePayment,
    db: AsyncSession = Depends(get_db_async),
    service: PaymentsService = Depends(payment_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.create_payment_order(payload, db)


@router.post("/order/verify-payment")
async def verify_payment(
    payload: VerifyPayment,
    db: AsyncSession = Depends(get_db_async),
    service: PaymentsService = Depends(payment_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.verify_payment(payload, db)
