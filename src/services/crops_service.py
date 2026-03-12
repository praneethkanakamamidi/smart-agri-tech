from fastapi import HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from src.data_models.crops_model import Crops
from src.data_models.miscellaneous_model import Miscellaneous_Data


class CropService:
    async def post_crop(self, payload, db: AsyncSession):
        try:
            stmt = select(Crops).where(
                func.lower(Crops.crop_name) == payload.crop_name.lower()
            )
            result = await db.execute(stmt)
            existing_crop_data = result.scalar_one_or_none()

            stmt_misc = select(Miscellaneous_Data).where(
                Miscellaneous_Data.category == "status",
                Miscellaneous_Data.value == "active",
            )
            res_misc = await db.execute(stmt_misc)
            active_misc_data = res_misc.scalar_one_or_none()

            if existing_crop_data:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Error: Crop of that name already exists",
                )

            new_crop = Crops(
                crop_name=payload.crop_name,
                crop_type=payload.crop_type,
                description=payload.description,
                created_by=payload.created_by,
                status=active_misc_data.id,
                created_at=datetime.now(),
            )
            db.add(new_crop)
            await db.commit()
            return {"message": f"Crop '{payload.crop_name}' has been successfully created!"}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def get_crop(self, id: int, db: AsyncSession):
        try:
            stmt = (
                select(Crops)
                .where(Crops.id == id)
                .options(
                    joinedload(Crops.status_rel),
                    joinedload(Crops.created_by_user),
                    joinedload(Crops.updated_by_user),
                )
            )
            result = await db.execute(stmt)
            crop_data = result.scalar_one_or_none()
            if crop_data:
                crop_data.created_user = crop_data.created_by_user.first_name if crop_data.created_by_user else None
                crop_data.updated_user = crop_data.updated_by_user.first_name if crop_data.updated_by_user else None
                crop_data.status_value = crop_data.status_rel.value if crop_data.status_rel else None
                return crop_data
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crop not found")
        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def get_crops(self, db: AsyncSession):
        try:
            stmt = (
                select(Crops)
                .order_by(Crops.created_at.desc())
                .options(joinedload(Crops.status_rel))
            )
            result = await db.execute(stmt)
            crop_data = result.scalars().unique().all()
            for crop in crop_data:
                crop.status_value = crop.status_rel.value if crop.status_rel else None
            return crop_data
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def put_crop(self, payload, db: AsyncSession):
        try:
            stmt = select(Crops).where(Crops.id == payload.id)
            result = await db.execute(stmt)
            existing_crop_data = result.scalar_one_or_none()
            if not existing_crop_data:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Error: Crop of that id does not exist",
                )
            existing_crop_data.crop_name = payload.crop_name
            existing_crop_data.crop_type = payload.crop_type
            existing_crop_data.description = payload.description
            existing_crop_data.updated_by = payload.updated_by
            existing_crop_data.updated_at = datetime.now()
            await db.commit()
            return {"message": "Crop has been updated"}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def crop_status(self, payload, db: AsyncSession):
        try:
            stmt = select(Crops).where(Crops.id == payload.id)
            result = await db.execute(stmt)
            existing_crop_data = result.scalar_one_or_none()

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

            if not existing_crop_data:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crop not found")
            if not inactive_misc_data or not active_misc_data:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Status data not found")

            initial_state = ""
            final_state = ""
            if existing_crop_data.status == inactive_misc_data.id:
                existing_crop_data.status = active_misc_data.id
                existing_crop_data.updated_by = payload.updated_by
                existing_crop_data.updated_at = datetime.now()
                await db.commit()
                initial_state, final_state = "inactive", "active"
            elif existing_crop_data.status == active_misc_data.id:
                existing_crop_data.status = inactive_misc_data.id
                existing_crop_data.updated_by = payload.updated_by
                existing_crop_data.updated_at = datetime.now()
                await db.commit()
                initial_state, final_state = "active", "inactive"

            return {"message": f"{existing_crop_data.crop_name} status has been changed from {initial_state} to {final_state}"}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )
