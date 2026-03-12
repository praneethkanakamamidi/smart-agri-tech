from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.payments_history_service import PaymentsHistory
from src.db_connections.database import get_db_async
from src.services.login_service import LoginService
from src.data_models.users_model import Users

router = APIRouter(prefix="/api", tags=["Payments_history"])

get_current_active_user = LoginService.get_current_active_user


def payments_history_service() -> PaymentsHistory:
    return PaymentsHistory()


@router.get("/farmer/payments_history/{id}")
async def farmer_payments_history(
    id: int,
    page: int = 1,
    page_size: int = 10,
    db: AsyncSession = Depends(get_db_async),
    service: PaymentsHistory = Depends(payments_history_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.farmer_payments_history(id, db, page, page_size)


@router.get("/vendor/payments_history/{id}")
async def vendor_payments_history(
    id: int,
    page: int = 1,
    page_size: int = 10,
    db: AsyncSession = Depends(get_db_async),
    service: PaymentsHistory = Depends(payments_history_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.vendor_payments_history(id, db, page, page_size)
