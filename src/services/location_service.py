from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data_models.states_model import States
from src.data_models.districts_model import Districts


class LocationService:
    async def get_states(self, db: AsyncSession):
        try:
            stmt = select(States)
            result = await db.execute(stmt)
            states_data = result.scalars().all()
            if not states_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="States not found",
                )
            return states_data
        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def get_districts(self, id: int, db: AsyncSession):
        try:
            stmt = select(Districts).where(Districts.state_id == id)
            result = await db.execute(stmt)
            districts_data = result.scalars().all()
            if not districts_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Districts not found for that state id",
                )
            return districts_data
        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )
