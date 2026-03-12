from fastapi import HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from src.data_models.fertilizers_model import Fertilizers
from src.data_models.miscellaneous_model import Miscellaneous_Data


class FertilizersService:
    async def post_fertilizer(self, payload, db: AsyncSession):
        try:
            stmt = select(Fertilizers).where(
                func.lower(Fertilizers.fertilizer_name) == payload.fertilizer_name.lower()
            )
            result = await db.execute(stmt)
            existing_fertilizer_data = result.scalar_one_or_none()

            stmt_misc = select(Miscellaneous_Data).where(
                Miscellaneous_Data.category == "status",
                Miscellaneous_Data.value == "active",
            )
            res_misc = await db.execute(stmt_misc)
            active_misc_data = res_misc.scalar_one_or_none()

            if existing_fertilizer_data:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Error: Fertilizer of that name already exists",
                )

            new_fertilizer = Fertilizers(
                fertilizer_name=payload.fertilizer_name,
                application_method=payload.application_method,
                description=payload.description,
                created_by=payload.created_by,
                status=active_misc_data.id,
                created_at=datetime.now(),
            )
            db.add(new_fertilizer)
            await db.commit()
            return {"message": f"Fertilizer '{payload.fertilizer_name}' has been successfully created!"}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def get_fertilizer(self, id: int, db: AsyncSession):
        try:
            stmt = (
                select(Fertilizers)
                .where(Fertilizers.id == id)
                .options(
                    joinedload(Fertilizers.status_rel),
                    joinedload(Fertilizers.created_by_user),
                    joinedload(Fertilizers.updated_by_user),
                )
            )
            result = await db.execute(stmt)
            fertilizer_data = result.scalar_one_or_none()
            if fertilizer_data:
                fertilizer_data.created_user = fertilizer_data.created_by_user.first_name if fertilizer_data.created_by_user else None
                fertilizer_data.updated_user = fertilizer_data.updated_by_user.first_name if fertilizer_data.updated_by_user else None
                fertilizer_data.status_value = fertilizer_data.status_rel.value if fertilizer_data.status_rel else None
                return fertilizer_data
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fertilizer not found")
        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def get_fertilizers(self, db: AsyncSession):
        try:
            stmt = (
                select(Fertilizers)
                .order_by(Fertilizers.created_at.desc())
                .options(joinedload(Fertilizers.status_rel))
            )
            result = await db.execute(stmt)
            fertilizer_data = result.scalars().unique().all()
            for fertilizer in fertilizer_data:
                fertilizer.status_value = fertilizer.status_rel.value if fertilizer.status_rel else None
            return fertilizer_data
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def put_fertilizer(self, payload, db: AsyncSession):
        try:
            stmt = select(Fertilizers).where(Fertilizers.id == payload.id)
            result = await db.execute(stmt)
            existing_fertilizer_data = result.scalar_one_or_none()
            if not existing_fertilizer_data:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Error: Fertilizer of that id does not exist",
                )
            existing_fertilizer_data.fertilizer_name = payload.fertilizer_name
            existing_fertilizer_data.application_method = payload.application_method
            existing_fertilizer_data.description = payload.description
            existing_fertilizer_data.updated_by = payload.updated_by
            existing_fertilizer_data.updated_at = datetime.now()
            await db.commit()
            return {"message": "Fertilizer has been updated"}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def fertilizer_status(self, payload, db: AsyncSession):
        try:
            stmt = select(Fertilizers).where(Fertilizers.id == payload.id)
            result = await db.execute(stmt)
            existing_fertilizer_data = result.scalar_one_or_none()

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

            if not existing_fertilizer_data:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fertilizer not found")
            if not inactive_misc_data or not active_misc_data:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Status data not found")

            initial_state, final_state = "", ""
            if existing_fertilizer_data.status == inactive_misc_data.id:
                existing_fertilizer_data.status = active_misc_data.id
                existing_fertilizer_data.updated_by = payload.updated_by
                existing_fertilizer_data.updated_at = datetime.now()
                await db.commit()
                initial_state, final_state = "inactive", "active"
            elif existing_fertilizer_data.status == active_misc_data.id:
                existing_fertilizer_data.status = inactive_misc_data.id
                existing_fertilizer_data.updated_by = payload.updated_by
                existing_fertilizer_data.updated_at = datetime.now()
                await db.commit()
                initial_state, final_state = "active", "inactive"

            return {"message": f"{existing_fertilizer_data.fertilizer_name} status has been changed from {initial_state} to {final_state}"}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )
