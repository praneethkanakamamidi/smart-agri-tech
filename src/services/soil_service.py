from fastapi import HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from src.data_models.soil_model import Soil
from src.data_models.miscellaneous_model import Miscellaneous_Data


class SoilService:
    async def post_soil(self, payload, db: AsyncSession):
        try:
            stmt = select(Soil).where(func.lower(Soil.soil_name) == payload.soil_name.lower())
            result = await db.execute(stmt)
            existing_soil_data = result.scalar_one_or_none()

            stmt_misc = select(Miscellaneous_Data).where(
                Miscellaneous_Data.category == "status",
                Miscellaneous_Data.value == "active",
            )
            res_misc = await db.execute(stmt_misc)
            active_misc_data = res_misc.scalar_one_or_none()

            if existing_soil_data:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Error: Soil of that name already exists",
                )

            new_soil = Soil(
                soil_name=payload.soil_name,
                soil_texture=payload.soil_texture,
                description=payload.description,
                created_by=payload.created_by,
                status=active_misc_data.id,
                created_at=datetime.now(),
            )
            db.add(new_soil)
            await db.commit()
            return {"message": f"Soil '{payload.soil_name}' has been successfully created!"}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def get_soil(self, id: int, db: AsyncSession):
        try:
            stmt = (
                select(Soil)
                .where(Soil.id == id)
                .options(
                    joinedload(Soil.status_rel),
                    joinedload(Soil.created_by_user),
                    joinedload(Soil.updated_by_user),
                )
            )
            result = await db.execute(stmt)
            soil_data = result.scalar_one_or_none()
            if soil_data:
                soil_data.created_user = soil_data.created_by_user.first_name if soil_data.created_by_user else None
                soil_data.updated_user = soil_data.updated_by_user.first_name if soil_data.updated_by_user else None
                soil_data.status_value = soil_data.status_rel.value if soil_data.status_rel else None
                return soil_data
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Soil not found")
        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def get_soils(self, db: AsyncSession):
        try:
            stmt = (
                select(Soil)
                .order_by(Soil.created_at.desc())
                .options(joinedload(Soil.status_rel))
            )
            result = await db.execute(stmt)
            soil_data = result.scalars().unique().all()
            for soil in soil_data:
                soil.status_value = soil.status_rel.value if soil.status_rel else None
            return soil_data
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def put_soil(self, payload, db: AsyncSession):
        try:
            stmt = select(Soil).where(Soil.id == payload.id)
            result = await db.execute(stmt)
            existing_soil_data = result.scalar_one_or_none()
            if not existing_soil_data:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Error: Soil of that id does not exist",
                )
            existing_soil_data.soil_name = payload.soil_name
            existing_soil_data.soil_texture = payload.soil_texture
            existing_soil_data.description = payload.description
            existing_soil_data.updated_by = payload.updated_by
            existing_soil_data.updated_at = datetime.now()
            await db.commit()
            return {"message": "Soil has been updated"}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def soil_status(self, payload, db: AsyncSession):
        try:
            stmt = select(Soil).where(Soil.id == payload.id)
            result = await db.execute(stmt)
            existing_soil_data = result.scalar_one_or_none()

            stmt_inactive = select(Miscellaneous_Data).where(
                Miscellaneous_Data.category == "status",
                Miscellaneous_Data.value == "inactive",
            )
            stmt_active = select(Miscellaneous_Data).where(
                Miscellaneous_Data.category == "status",
                Miscellaneous_Data.value == "active",
            )
            res_inactive = await db.execute(stmt_inactive)
            res_active = await db.execute(stmt_active)
            inactive_misc_data = res_inactive.scalar_one_or_none()
            active_misc_data = res_active.scalar_one_or_none()

            if not existing_soil_data:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Soil not found")
            if not inactive_misc_data or not active_misc_data:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Status data not found")

            initial_state, final_state = "", ""
            if existing_soil_data.status == inactive_misc_data.id:
                existing_soil_data.status = active_misc_data.id
                existing_soil_data.updated_by = payload.updated_by
                existing_soil_data.updated_at = datetime.now()
                await db.commit()
                initial_state, final_state = "inactive", "active"
            elif existing_soil_data.status == active_misc_data.id:
                existing_soil_data.status = inactive_misc_data.id
                existing_soil_data.updated_by = payload.updated_by
                existing_soil_data.updated_at = datetime.now()
                await db.commit()
                initial_state, final_state = "active", "inactive"

            return {"message": f"{existing_soil_data.soil_name} status has been changed from {initial_state} to {final_state}"}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )
