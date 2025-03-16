from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.services.payments_history_service import PaymentsHistory
from src.db_connections.postgresql_conn import get_db
from src.services.login_service import LoginService
from src.data_models.users_model import Users
from fastapi import Query

router = APIRouter(prefix="/api", tags=["Payments_history"])

get_current_active_user = LoginService.get_current_active_user

def payments_history_service() -> PaymentsHistory:
    return PaymentsHistory()

@router.get("/farmer/payments_history/{id}")
def get_farmer_payments_history(
    id: int, 
    page: int = Query(1, alias="page", description="Page number (1-based)"),
    page_size: int = Query(10, alias="page_size", description="Number of records per page"),
    db: Session = Depends(get_db), 
    service: PaymentsHistory = Depends(payments_history_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.farmer_payments_history(id, db, page, page_size)
    return response

@router.get("/vendor/payments_history/{id}")
def get_vendor_payments_history(
    id: int, 
    page: int = Query(1, alias="page", description="Page number (1-based)"),
    page_size: int = Query(10, alias="page_size", description="Number of records per page"),
    db: Session = Depends(get_db), 
    service: PaymentsHistory = Depends(payments_history_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.vendor_payments_history(id, db, page, page_size)
    return response
