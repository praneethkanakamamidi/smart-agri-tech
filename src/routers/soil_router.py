from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.soil_service import SoilService
from src.db_connections.database import get_db_async
from src.services.login_service import LoginService
from src.data_models.users_model import Users
from src.security_utils.role_guard import require_roles, ADMIN
from src.schemas.soil_schema import SoilSchema, UpdateSoilSchema, SoilStatus

router = APIRouter(prefix="/api", tags=["Soil"])

get_current_active_user = LoginService.get_current_active_user


def soil_service() -> SoilService:
    return SoilService()


@router.post("/soil/")
async def post_soil_data(
    payload: SoilSchema,
    db: AsyncSession = Depends(get_db_async),
    service: SoilService = Depends(soil_service),
    user: Users = Depends(require_roles(ADMIN)),
):
    if hasattr(payload, 'created_by'):
        payload.created_by = user.id
    if hasattr(payload, 'updated_by'):
        payload.updated_by = user.id
    return await service.post_soil(payload, db)


@router.put("/soil/")
async def put_soil_data(
    payload: UpdateSoilSchema,
    db: AsyncSession = Depends(get_db_async),
    service: SoilService = Depends(soil_service),
    user: Users = Depends(require_roles(ADMIN)),
):
    if hasattr(payload, 'created_by'):
        payload.created_by = user.id
    if hasattr(payload, 'updated_by'):
        payload.updated_by = user.id
    return await service.put_soil(payload, db)


@router.get("/soil/{id}")
async def get_soil_data(
    id: int,
    db: AsyncSession = Depends(get_db_async),
    service: SoilService = Depends(soil_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.get_soil(id, db)


@router.get("/soil/")
async def get_soils_data(
    db: AsyncSession = Depends(get_db_async),
    service: SoilService = Depends(soil_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.get_soils(db)


@router.put("/soil-status/")
async def soil_data_status(
    payload: SoilStatus,
    db: AsyncSession = Depends(get_db_async),
    service: SoilService = Depends(soil_service),
    user: Users = Depends(require_roles(ADMIN)),
):
    if hasattr(payload, 'created_by'):
        payload.created_by = user.id
    if hasattr(payload, 'updated_by'):
        payload.updated_by = user.id
    return await service.soil_status(payload, db)
