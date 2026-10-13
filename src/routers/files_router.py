from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.data_models.users_model import Users
from src.db_connections.database import get_db_async
from src.security_utils.role_guard import current_user_with_role
from src.services.files_service import FilesService

router = APIRouter(prefix="/api", tags=["Files"])


def files_service() -> FilesService:
    return FilesService()


@router.post("/files")
async def upload_file(
    file: UploadFile = File(...),
    purpose: str = Form(...),
    db: AsyncSession = Depends(get_db_async),
    service: FilesService = Depends(files_service),
    user: Users = Depends(current_user_with_role),
):
    """Upload an image or PDF, then reference its `file_id` from a listing, message, dispute, etc."""
    return await service.upload(user, file, purpose, db)


@router.get("/files/{file_id}")
async def download_file(
    file_id: str,
    db: AsyncSession = Depends(get_db_async),
    service: FilesService = Depends(files_service),
    user: Users = Depends(current_user_with_role),
):
    return await service.download(file_id, user, user.role_name, db)


@router.delete("/files/{file_id}")
async def delete_file(
    file_id: str,
    db: AsyncSession = Depends(get_db_async),
    service: FilesService = Depends(files_service),
    user: Users = Depends(current_user_with_role),
):
    return await service.delete(file_id, user, db)
