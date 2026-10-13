from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.fertilizers_service import FertilizersService
from src.db_connections.database import get_db_async
from src.services.login_service import LoginService
from src.data_models.users_model import Users
from src.security_utils.role_guard import require_roles, ADMIN
from src.schemas.fertilizers_schema import FertilizerSchema, UpdateFertilizerSchema, FertilizerStatus

router = APIRouter(prefix="/api", tags=["Fertilizers"])

get_current_active_user = LoginService.get_current_active_user


def fertilizers_service() -> FertilizersService:
    return FertilizersService()


@router.post("/fertilizers/")
async def post_fertilizers_data(
    payload: FertilizerSchema,
    db: AsyncSession = Depends(get_db_async),
    service: FertilizersService = Depends(fertilizers_service),
    user: Users = Depends(require_roles(ADMIN)),
):
    if hasattr(payload, 'created_by'):
        payload.created_by = user.id
    if hasattr(payload, 'updated_by'):
        payload.updated_by = user.id
    return await service.post_fertilizer(payload, db)


@router.put("/fertilizers/")
async def put_fertilizers_data(
    payload: UpdateFertilizerSchema,
    db: AsyncSession = Depends(get_db_async),
    service: FertilizersService = Depends(fertilizers_service),
    user: Users = Depends(require_roles(ADMIN)),
):
    if hasattr(payload, 'created_by'):
        payload.created_by = user.id
    if hasattr(payload, 'updated_by'):
        payload.updated_by = user.id
    return await service.put_fertilizer(payload, db)


@router.get("/fertilizer/{id}")
async def get_fertilizer_data(
    id: int,
    db: AsyncSession = Depends(get_db_async),
    service: FertilizersService = Depends(fertilizers_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.get_fertilizer(id, db)


@router.get("/fertilizers/")
async def get_fertilizers_data(
    db: AsyncSession = Depends(get_db_async),
    service: FertilizersService = Depends(fertilizers_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.get_fertilizers(db)


@router.put("/fertilizers-status/")
async def fertilizer_data_status(
    payload: FertilizerStatus,
    db: AsyncSession = Depends(get_db_async),
    service: FertilizersService = Depends(fertilizers_service),
    user: Users = Depends(require_roles(ADMIN)),
):
    if hasattr(payload, 'created_by'):
        payload.created_by = user.id
    if hasattr(payload, 'updated_by'):
        payload.updated_by = user.id
    return await service.fertilizer_status(payload, db)
