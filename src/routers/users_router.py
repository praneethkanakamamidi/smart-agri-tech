from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.users_service import UsersService
from src.schemas.users_schema import (
    Add_User, VerifyUserOtp, UpdateProfileSchema, ChangeContactSchema, VerifyContactSchema, PasswordConfirmSchema,
)
from src.db_connections.database import get_db_async
from src.data_models.users_model import Users
from src.services.login_service import LoginService
from src.security_utils.role_guard import require_roles, ADMIN


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
    """Register as a farmer or vendor with a mobile number and/or email. A code is sent to verify it."""
    return await users_service.add_user(payload, db)


@router.post("/verify-otp")
async def verify_user_otp(
    payload: VerifyUserOtp,
    db: AsyncSession = Depends(get_db_async),
    users_service: UsersService = Depends(users_service),
):
    return await users_service.verify_user_otp(payload, db)


# Declared before /users/{id} so "me" isn't parsed as an id.
@router.get("/users/me")
async def get_my_profile(
    db: AsyncSession = Depends(get_db_async),
    users_service: UsersService = Depends(users_service),
    user: Users = Depends(get_current_active_user),
):
    return await users_service.get_profile(user.id, db)


@router.put("/users/me")
async def update_my_profile(
    payload: UpdateProfileSchema,
    db: AsyncSession = Depends(get_db_async),
    users_service: UsersService = Depends(users_service),
    user: Users = Depends(get_current_active_user),
):
    return await users_service.update_profile(user.id, payload, db)


@router.post("/users/me/contact")
async def change_contact(
    payload: ChangeContactSchema,
    db: AsyncSession = Depends(get_db_async),
    users_service: UsersService = Depends(users_service),
    user: Users = Depends(get_current_active_user),
):
    return await users_service.change_contact(user, payload, db)


@router.post("/users/me/contact/verify")
async def verify_contact(
    payload: VerifyContactSchema,
    db: AsyncSession = Depends(get_db_async),
    users_service: UsersService = Depends(users_service),
    user: Users = Depends(get_current_active_user),
):
    return await users_service.verify_contact(user, payload, db)


@router.post("/users/me/deactivate")
async def deactivate_account(
    payload: PasswordConfirmSchema,
    db: AsyncSession = Depends(get_db_async),
    users_service: UsersService = Depends(users_service),
    user: Users = Depends(get_current_active_user),
):
    return await users_service.deactivate(user, payload, db)


@router.post("/users/me/deletion-request")
async def request_deletion(
    payload: PasswordConfirmSchema,
    db: AsyncSession = Depends(get_db_async),
    users_service: UsersService = Depends(users_service),
    user: Users = Depends(get_current_active_user),
):
    return await users_service.request_deletion(user, payload, db)


@router.delete("/users/me/deletion-request")
async def cancel_deletion(
    db: AsyncSession = Depends(get_db_async),
    users_service: UsersService = Depends(users_service),
    user: Users = Depends(get_current_active_user),
):
    return await users_service.cancel_deletion(user, db)


@router.get("/users/{id}")
async def get_user(
    id: int,
    db: AsyncSession = Depends(get_db_async),
    users_service: UsersService = Depends(users_service),
    user: Users = Depends(require_roles(ADMIN)),
):
    return await users_service.get_user(id, db)


@router.get("/users/")
async def get_users(
    db: AsyncSession = Depends(get_db_async),
    users_service: UsersService = Depends(users_service),
    user: Users = Depends(require_roles(ADMIN)),
):
    return await users_service.get_all_users(db)


@router.get("/user-status/{id}", deprecated=True)
async def user_status(
    id: int,
    db: AsyncSession = Depends(get_db_async),
    users_service: UsersService = Depends(users_service),
    user: Users = Depends(require_roles(ADMIN)),
):
    """Deprecated: use PUT /api/admin/users/{id}/status."""
    return await users_service.activate_deactivate_user(id, db, user.id)
