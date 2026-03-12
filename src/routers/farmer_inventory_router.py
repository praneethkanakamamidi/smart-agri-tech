from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.farmer_inventory_service import FarmerInventoryService
from src.db_connections.database import get_db_async
from src.services.login_service import LoginService
from src.data_models.users_model import Users
from src.schemas.farmer_inventory_schema import AddFarmerInventorySchema, UpdateFarmerInventorySchema

router = APIRouter(prefix="/api", tags=["Inventory"])

get_current_active_user = LoginService.get_current_active_user


def farmer_inventory_service() -> FarmerInventoryService:
    return FarmerInventoryService()


@router.post("/inventory/")
async def post_stock_data(
    payload: AddFarmerInventorySchema,
    db: AsyncSession = Depends(get_db_async),
    service: FarmerInventoryService = Depends(farmer_inventory_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.post_stock(payload, db)


@router.put("/inventory/")
async def put_stock_data(
    payload: UpdateFarmerInventorySchema,
    db: AsyncSession = Depends(get_db_async),
    service: FarmerInventoryService = Depends(farmer_inventory_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.put_stock(payload, db)


@router.get("/inventory/stock/{id}")
async def get_stock_data(
    id: int,
    db: AsyncSession = Depends(get_db_async),
    service: FarmerInventoryService = Depends(farmer_inventory_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.get_stock(id, db)


@router.get("/inventory/stocks/{user_id}")
async def get_stocks_data(
    user_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: FarmerInventoryService = Depends(farmer_inventory_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.get_stocks(user_id, db)


@router.delete("/delete-stock/{id}")
async def stock_data_status(
    id: int,
    db: AsyncSession = Depends(get_db_async),
    service: FarmerInventoryService = Depends(farmer_inventory_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.delete_stock(id, db)
