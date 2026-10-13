from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.crops_service import CropService
from src.db_connections.database import get_db_async
from src.services.login_service import LoginService
from src.data_models.users_model import Users
from src.security_utils.role_guard import require_roles, ADMIN
from src.schemas.crops_schema import CropsSchema, UpdateCropSchema, CropStatus

router = APIRouter(prefix="/api", tags=["Crops"])

get_current_active_user = LoginService.get_current_active_user


def crops_service() -> CropService:
    return CropService()


@router.post("/crops/")
async def post_crops_data(
    payload: CropsSchema,
    db: AsyncSession = Depends(get_db_async),
    service: CropService = Depends(crops_service),
    user: Users = Depends(require_roles(ADMIN)),
):
    if hasattr(payload, 'created_by'):
        payload.created_by = user.id
    if hasattr(payload, 'updated_by'):
        payload.updated_by = user.id
    return await service.post_crop(payload, db)


@router.put("/crops/")
async def put_crops_data(
    payload: UpdateCropSchema,
    db: AsyncSession = Depends(get_db_async),
    service: CropService = Depends(crops_service),
    user: Users = Depends(require_roles(ADMIN)),
):
    if hasattr(payload, 'created_by'):
        payload.created_by = user.id
    if hasattr(payload, 'updated_by'):
        payload.updated_by = user.id
    return await service.put_crop(payload, db)


@router.get("/crops/{id}")
async def get_crop_data(
    id: int,
    db: AsyncSession = Depends(get_db_async),
    service: CropService = Depends(crops_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.get_crop(id, db)


@router.get("/crops/")
async def get_crops_data(
    db: AsyncSession = Depends(get_db_async),
    service: CropService = Depends(crops_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.get_crops(db)


@router.put("/crops-status/")
async def crop_data_status(
    payload: CropStatus,
    db: AsyncSession = Depends(get_db_async),
    service: CropService = Depends(crops_service),
    user: Users = Depends(require_roles(ADMIN)),
):
    if hasattr(payload, 'created_by'):
        payload.created_by = user.id
    if hasattr(payload, 'updated_by'):
        payload.updated_by = user.id
    return await service.crop_status(payload, db)
