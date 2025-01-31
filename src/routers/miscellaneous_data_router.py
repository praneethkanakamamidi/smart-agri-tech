from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.services.miscellaneous_service import MiscellaneousDataService
from src.db_connections.postgresql_conn import get_db
from src.services.login_service import LoginService
from src.data_models.users_model import Users

router = APIRouter(prefix="/api")

def get_miscellaneous_data_service() -> MiscellaneousDataService:
    return MiscellaneousDataService()

@router.get("/miscellaneous/{id}")
def get_miscellaneous_data(
    id: int, 
    db: Session = Depends(get_db), 
    service: MiscellaneousDataService = Depends(get_miscellaneous_data_service),
    current_user: Users=Depends(LoginService.get_current_user)
):
    response = service.get_miscellaneous_data(id, db)
    return response
