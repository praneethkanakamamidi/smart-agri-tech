from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.services.location_service import LocationService
from src.db_connections.postgresql_conn import get_db
from src.services.login_service import LoginService
from src.data_models.users_model import Users

router = APIRouter(prefix="/api", tags=["Location"])

get_current_active_user = LoginService.get_current_active_user

def location_service() -> LocationService:
    return LocationService()

@router.post("/states/")
def get_states(
    db: Session = Depends(get_db),
    service: LocationService = Depends(location_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.get_states(db)
    return response

@router.put("/districts/{id}")
def get_districts(
    id: int,
    db: Session = Depends(get_db), 
    service: LocationService = Depends(location_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.get_districts(id, db)
    return response

