from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.login_service import LoginService
from src.db_connections.database import get_db_async
from fastapi.security import OAuth2PasswordRequestForm

router = APIRouter(prefix="/api")


def login_service() -> LoginService:
    return LoginService()


@router.post("/login/")
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db_async),
    service: LoginService = Depends(login_service),
):
    return await service.login(form_data, db)
