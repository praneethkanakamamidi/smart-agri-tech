from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data_models.miscellaneous_model import Miscellaneous_Data


class MiscellaneousDataService:
    async def get_miscellaneous_data(self, id: int, db: AsyncSession):
        try:
            stmt = select(Miscellaneous_Data).where(Miscellaneous_Data.id == id)
            result = await db.execute(stmt)
            miscellaneous_data_values = result.scalar_one_or_none()
            if not miscellaneous_data_values:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Miscellaneous data not found",
                )
            return miscellaneous_data_values
        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e),
                headers={"Content-Type": "application/json"},
            )
