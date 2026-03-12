from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.miscellaneous_service import MiscellaneousDataService
from src.db_connections.database import get_db_async

router = APIRouter(prefix="/api", tags=["Miscellaneous"])


def get_miscellaneous_data_service() -> MiscellaneousDataService:
    return MiscellaneousDataService()


@router.get("/miscellaneous/{id}")
async def get_miscellaneous_data(
    id: int,
    db: AsyncSession = Depends(get_db_async),
    service: MiscellaneousDataService = Depends(get_miscellaneous_data_service),
):
    return await service.get_miscellaneous_data(id, db)
