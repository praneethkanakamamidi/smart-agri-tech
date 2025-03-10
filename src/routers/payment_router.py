from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.services.payment_service import PaymentsService
from src.db_connections.postgresql_conn import get_db
from src.services.login_service import LoginService
from src.data_models.users_model import Users
from src.schemas.payment_schema import CreatePayment, VerifyPayment

router = APIRouter(prefix="/api", tags=["Payments"])

get_current_active_user = LoginService.get_current_active_user

def payment_service() -> PaymentsService:
    return PaymentsService()

@router.post("/order/payment")
def post_soil_data(
    payload: CreatePayment,
    db: Session = Depends(get_db),
    service: PaymentsService = Depends(payment_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.create_payment_order(payload, db)
    return response

@router.post("/order/verify-payment")
def post_soil_data(
    payload: VerifyPayment,
    db: Session = Depends(get_db),
    service: PaymentsService = Depends(payment_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.verify_payment(payload, db)
    return response