from fastapi import APIRouter, Depends, HTTPException, Query
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
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db_async),
    service: PaymentsHistory = Depends(payments_history_service),
    user: Users = Depends(get_current_active_user),
):
    if user.id != id:
        raise HTTPException(status_code=403, detail="You can only view your own payment history.")
    return await service.farmer_payments_history(id, db, page, page_size)


@router.get("/vendor/payments_history/{id}")
async def vendor_payments_history(
    id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db_async),
    service: PaymentsHistory = Depends(payments_history_service),
    user: Users = Depends(get_current_active_user),
):
    if user.id != id:
        raise HTTPException(status_code=403, detail="You can only view your own payment history.")
    return await service.vendor_payments_history(id, db, page, page_size)
