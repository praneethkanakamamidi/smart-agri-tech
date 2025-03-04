from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.services.farmer_inventory_service import FarmerInventoryService
from src.db_connections.postgresql_conn import get_db
from src.services.login_service import LoginService
from src.data_models.users_model import Users
from src.schemas.farmer_inventory_schema import AddFarmerInventorySchema, UpdateFarmerInventorySchema

router = APIRouter(prefix="/api", tags=["Inventory"])

get_current_active_user = LoginService.get_current_active_user

def farmer_inventory_service() -> FarmerInventoryService:
    return FarmerInventoryService()

@router.post("/inventory/")
def post_stock_data(
    payload: AddFarmerInventorySchema,
    db: Session = Depends(get_db),
    service: FarmerInventoryService = Depends(farmer_inventory_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.post_stock(payload, db)
    return response

@router.put("/inventory/")
def put_stock_data(
    payload: UpdateFarmerInventorySchema,
    db: Session = Depends(get_db), 
    service: FarmerInventoryService = Depends(farmer_inventory_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.put_stock(payload, db)
    return response

@router.get("/inventory/stock/{id}")
def get_stock_data(
    id: int, 
    db: Session = Depends(get_db), 
    service: FarmerInventoryService = Depends(farmer_inventory_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.get_stock(id, db)
    return response

@router.get("/inventory/stocks/{user_id}")
def get_stocks_data(
    user_id: int,
    db: Session = Depends(get_db), 
    service: FarmerInventoryService = Depends(farmer_inventory_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.get_stocks(user_id, db)
    return response

@router.delete("/delete-stock/{id}")
def stock_data_status(
    id: int, 
    db: Session = Depends(get_db), 
    service: FarmerInventoryService = Depends(farmer_inventory_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.delete_stock(id, db)
    return response