from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.users_service import UsersService
from src.schemas.users_schema import Add_User, VerifyUserOtp
from src.db_connections.database import get_db_async
from src.data_models.users_model import Users
from src.services.login_service import LoginService


def users_service() -> UsersService:
    return UsersService()


router = APIRouter(prefix="/api", tags=["Users"])

get_current_active_user = LoginService.get_current_active_user


@router.post("/users")
async def create_user(
    payload: Add_User,
    db: AsyncSession = Depends(get_db_async),
    users_service: UsersService = Depends(users_service),
):
    return await users_service.add_user(payload, db)


@router.post("/verify-otp")
async def verify_user_otp(
    payload: VerifyUserOtp,
    db: AsyncSession = Depends(get_db_async),
    users_service: UsersService = Depends(users_service),
):
    return await users_service.verify_user_otp(payload, db)


@router.get("/users/{id}")
async def get_user(
    id: int,
    db: AsyncSession = Depends(get_db_async),
    users_service: UsersService = Depends(users_service),
    user: Users = Depends(get_current_active_user),
):
    return await users_service.get_user(id, db)


@router.get("/users/")
async def get_users(
    db: AsyncSession = Depends(get_db_async),
    users_service: UsersService = Depends(users_service),
    user: Users = Depends(get_current_active_user),
):
    return await users_service.get_all_users(db)


@router.get("/user-status/{id}")
async def user_status(
    id: int,
    db: AsyncSession = Depends(get_db_async),
    users_service: UsersService = Depends(users_service),
    user: Users = Depends(get_current_active_user),
):
    return await users_service.activate_deactivate_user(id, db)
