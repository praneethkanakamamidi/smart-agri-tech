from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.services.login_service import LoginService
from src.db_connections.postgresql_conn import get_db
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

router = APIRouter(prefix="/api")

def login_service() -> LoginService:
    return LoginService()

@router.post("/login/")
def get_miscellaneous_data(
    form_data: OAuth2PasswordRequestForm = Depends(), 
    db: Session = Depends(get_db), 
    service: LoginService = Depends(login_service)
):
    response = service.login(form_data, db)
    return response
