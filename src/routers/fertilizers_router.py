from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.services.fertilizers_service import FertilizersService
from src.db_connections.postgresql_conn import get_db
from src.services.login_service import LoginService
from src.data_models.users_model import Users
from src.schemas.fertilizers_schema import FertilizerSchema, UpdateFertilizerSchema, FertilizerStatus

router = APIRouter(prefix="/api", tags=["Fertilizers"])

get_current_active_user = LoginService.get_current_active_user

def fertilizers_service() -> FertilizersService:
    return FertilizersService()

@router.post("/fertilizers/")
def post_fertilizers_data(
    payload: FertilizerSchema,
    db: Session = Depends(get_db),
    service: FertilizersService = Depends(fertilizers_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.post_fertilizer(payload, db)
    return response

@router.put("/fertilizers/")
def put_fertilizers_data(
    payload: UpdateFertilizerSchema,
    db: Session = Depends(get_db), 
    service: FertilizersService = Depends(fertilizers_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.put_fertilizer(payload, db)
    return response

@router.get("/fertilizer/{id}")
def get_fertilizer_data(
    id: int, 
    db: Session = Depends(get_db), 
    service: FertilizersService = Depends(fertilizers_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.get_fertilizer(id, db)
    return response

@router.get("/fertilizers/")
def get_fertilizers_data(
    db: Session = Depends(get_db), 
    service: FertilizersService = Depends(fertilizers_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.get_fertilizers(db)
    return response

@router.put("/fertilizers-status/")
def fertilizers_data_status(
    payload: FertilizerStatus,
    db: Session = Depends(get_db), 
    service: FertilizersService = Depends(fertilizers_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.fertilizer_status(payload, db)
    return response