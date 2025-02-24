from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.services.soil_service import SoilService
from src.db_connections.postgresql_conn import get_db
from src.services.login_service import LoginService
from src.data_models.users_model import Users
from src.schemas.soil_schema import SoilSchema, UpdateSoilSchema, SoilStatus

router = APIRouter(prefix="/api", tags=["Soil"])

get_current_active_user = LoginService.get_current_active_user

def soil_service() -> SoilService:
    return SoilService()

@router.post("/soil/")
def post_soil_data(
    payload: SoilSchema,
    db: Session = Depends(get_db),
    service: SoilService = Depends(soil_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.post_soil(payload, db)
    return response

@router.put("/soil/")
def put_soil_data(
    payload: UpdateSoilSchema,
    db: Session = Depends(get_db), 
    service: SoilService = Depends(soil_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.put_soil(payload, db)
    return response

@router.get("/soil/{id}")
def get_soil_data(
    id: int, 
    db: Session = Depends(get_db), 
    service: SoilService = Depends(soil_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.get_soil(id, db)
    return response

@router.get("/soil/")
def get_soil_data(
    db: Session = Depends(get_db), 
    service: SoilService = Depends(soil_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.get_soil(db)
    return response

@router.put("/soil-status/")
def soil_data_status(
    payload: SoilStatus,
    db: Session = Depends(get_db), 
    service: SoilService = Depends(soil_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.soil_status(payload, db)
    return response