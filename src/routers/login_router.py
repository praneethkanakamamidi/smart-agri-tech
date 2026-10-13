from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from src.data_models.users_model import Users
from src.db_connections.database import get_db_async
from src.schemas.users_schema import (
    RefreshTokenSchema, LogoutSchema, MfaLoginSchema, MfaCodeSchema, PasswordResetRequestSchema,
    PasswordResetConfirmSchema, ChangePasswordSchema, AppealSchema, ResendOtpSchema,
)
from src.services.login_service import LoginService
from src.services.users_service import UsersService

router = APIRouter(prefix="/api", tags=["Authentication"])

get_current_active_user = LoginService.get_current_active_user


def login_service() -> LoginService:
    return LoginService()


def users_service() -> UsersService:
    return UsersService()


@router.post("/login/")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db_async),
    service: LoginService = Depends(login_service),
):
    """Log in with email, mobile number or username. Send an `X-Device-Name` header to label the session."""
    return await service.login(form_data, db, request)


@router.post("/login/mfa")
async def login_mfa(
    payload: MfaLoginSchema,
    request: Request,
    db: AsyncSession = Depends(get_db_async),
    service: LoginService = Depends(login_service),
):
    return await service.login_mfa(payload.mfa_token, payload.code, db, request)


@router.post("/token/refresh")
async def refresh_token(
    payload: RefreshTokenSchema,
    request: Request,
    db: AsyncSession = Depends(get_db_async),
    service: LoginService = Depends(login_service),
):
    return await service.refresh_access_token(payload.refresh_token, db, request)


@router.post("/auth/logout")
async def logout(
    payload: LogoutSchema,
    db: AsyncSession = Depends(get_db_async),
    service: LoginService = Depends(login_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.logout(user, getattr(user, "session_id", None), payload.all_devices, db)


@router.get("/auth/sessions")
async def list_sessions(
    db: AsyncSession = Depends(get_db_async),
    service: LoginService = Depends(login_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.list_sessions(user, getattr(user, "session_id", None), db)


@router.delete("/auth/sessions/{session_id}")
async def revoke_session(
    session_id: str,
    db: AsyncSession = Depends(get_db_async),
    service: LoginService = Depends(login_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.revoke_session(user, session_id, db)


@router.post("/auth/otp/resend")
async def resend_otp(
    payload: ResendOtpSchema,
    db: AsyncSession = Depends(get_db_async),
    service: UsersService = Depends(users_service),
):
    return await service.resend_otp(payload.identifier, db)


@router.post("/auth/password-reset/request")
async def request_password_reset(
    payload: PasswordResetRequestSchema,
    db: AsyncSession = Depends(get_db_async),
    service: UsersService = Depends(users_service),
):
    return await service.request_password_reset(payload.identifier, db)


@router.post("/auth/password-reset/confirm")
async def confirm_password_reset(
    payload: PasswordResetConfirmSchema,
    db: AsyncSession = Depends(get_db_async),
    service: UsersService = Depends(users_service),
):
    return await service.confirm_password_reset(payload, db)


@router.post("/auth/password/change")
async def change_password(
    payload: ChangePasswordSchema,
    db: AsyncSession = Depends(get_db_async),
    service: UsersService = Depends(users_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.change_password(user, payload, db)


@router.post("/auth/mfa/setup")
async def mfa_setup(
    db: AsyncSession = Depends(get_db_async),
    service: UsersService = Depends(users_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.mfa_setup(user, db)


@router.post("/auth/mfa/enable")
async def mfa_enable(
    payload: MfaCodeSchema,
    db: AsyncSession = Depends(get_db_async),
    service: UsersService = Depends(users_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.mfa_enable(user, payload.code, db)


@router.post("/auth/mfa/disable")
async def mfa_disable(
    payload: MfaCodeSchema,
    db: AsyncSession = Depends(get_db_async),
    service: UsersService = Depends(users_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.mfa_disable(user, payload.code, db)


@router.post("/appeals")
async def submit_appeal(
    payload: AppealSchema,
    db: AsyncSession = Depends(get_db_async),
    service: UsersService = Depends(users_service),
):
    return await service.submit_appeal(payload, db)
