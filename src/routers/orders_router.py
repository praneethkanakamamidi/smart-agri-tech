from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.services.orders_service import OrdersService
from src.db_connections.postgresql_conn import get_db
from src.services.login_service import LoginService
from src.data_models.users_model import Users
from src.schemas.orders_schema import PostOrderSchema, UpdateOrderStatus

router = APIRouter(prefix="/api", tags=["Orders"])

get_current_active_user = LoginService.get_current_active_user

def orders_service() -> OrdersService:
    return OrdersService()

@router.post("/order/")
def post_order(
    payload: PostOrderSchema,
    db: Session = Depends(get_db),
    service: OrdersService = Depends(orders_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.post_order(payload, db)
    return response

@router.get("/vendor/orders/")
def get_vendor_oders(
    id: int,
    db: Session = Depends(get_db), 
    service: OrdersService = Depends(orders_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.get_vendor_orders(id, db)
    return response

@router.get("/farmer/orders/")
def get_vendor_oders(
    id: int,
    db: Session = Depends(get_db), 
    service: OrdersService = Depends(orders_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.get_farmer_orders(id, db)
    return response

@router.put("/order-status/")
def order_status(
    payload: UpdateOrderStatus,
    db: Session = Depends(get_db), 
    service: OrdersService = Depends(orders_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.order_status(payload, db)
    return response