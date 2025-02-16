from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from src.services.users_service import UsersService
from src.schemas.users_schema import Add_User, VerifyUserOtp
from src.db_connections.postgresql_conn import get_db  # Import database session
from src.data_models.users_model import Users
from src.services.login_service import LoginService

def users_service() -> UsersService:
    return UsersService()

router = APIRouter(prefix="/api", tags=["Users"])

get_current_active_user = LoginService.get_current_active_user

@router.post("/users")
async def create_user(
    payload: Add_User,
    db: Session = Depends(get_db),
    users_service: UsersService = Depends(users_service),
):
    response = await users_service.add_user(payload, db)  # Ensure await
    return response

@router.post("/verify-otp")
async def verify_user_otp(
    payload: VerifyUserOtp,
    db: Session = Depends(get_db),
    users_service: UsersService = Depends(users_service),
):
    response = await users_service.verify_user_otp(payload, db)
    return response

@router.get("/users/{id}")
def get_user(
    id: int,
    db: Session = Depends(get_db),
    users_service: UsersService = Depends(users_service),
    user: Users = Depends(get_current_active_user)
):
    response = users_service.get_user(id, db) 
    return response


@router.get("/users/")
def get_users(
    db: Session = Depends(get_db),
    users_service: UsersService = Depends(users_service),
    user: Users = Depends(get_current_active_user)
):
    response = users_service.get_all_users(db) 
    return response
