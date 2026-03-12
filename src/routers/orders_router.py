from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.orders_service import OrdersService
from src.db_connections.database import get_db_async
from src.services.login_service import LoginService
from src.data_models.users_model import Users
from src.schemas.orders_schema import PostOrderSchema, UpdateOrderStatus

router = APIRouter(prefix="/api", tags=["Orders"])

get_current_active_user = LoginService.get_current_active_user


def orders_service() -> OrdersService:
    return OrdersService()


@router.post("/order/")
async def post_order(
    payload: PostOrderSchema,
    db: AsyncSession = Depends(get_db_async),
    service: OrdersService = Depends(orders_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.post_order(payload, db)


@router.get("/vendor/orders/")
async def get_vendor_orders(
    id: int,
    db: AsyncSession = Depends(get_db_async),
    service: OrdersService = Depends(orders_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.get_vendor_orders(id, db)


@router.get("/farmer/orders/")
async def get_farmer_orders(
    id: int,
    db: AsyncSession = Depends(get_db_async),
    service: OrdersService = Depends(orders_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.get_farmer_orders(id, db)


@router.put("/order-status/")
async def order_status(
    payload: UpdateOrderStatus,
    db: AsyncSession = Depends(get_db_async),
    service: OrdersService = Depends(orders_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.order_status(payload, db)
