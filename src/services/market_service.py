from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from src.data_models.farmer_inventory_model import FarmerInventory
from src.data_models.users_model import Users
from src.data_models.states_model import States
from src.data_models.districts_model import Districts
from src.data_models.crops_model import Crops
from src.data_models.soil_model import Soil
from src.data_models.fertilizers_model import Fertilizers


class MarketService:
    async def get_market(self, db: AsyncSession) -> list:
        try:
            stmt = (
                select(FarmerInventory)
                .options(
                    joinedload(FarmerInventory.crop_rel),
                    joinedload(FarmerInventory.soil_rel),
                    joinedload(FarmerInventory.fertilizer_rel),
                    joinedload(FarmerInventory.created_by_user).options(
                        joinedload(Users.state_rel),
                        joinedload(Users.district_rel),
                    ),
                )
            )
            result = await db.execute(stmt)
            market_data = result.scalars().unique().all()

            for data in market_data:
                user = data.created_by_user
                user_state = user.state_rel if user else None
                user_district = user.district_rel if user else None
                data.farmer_name = f"{user.first_name} {user.last_name}" if user else None
                data.state = user_state.state_name if user_state else None
                data.district = user_district.district_name if user_district else None
                data.crop_name = data.crop_rel.crop_name if data.crop_rel else None
                data.soil_name = data.soil_rel.soil_name if data.soil_rel else None
                data.fertilizer_name = data.fertilizer_rel.fertilizer_name if data.fertilizer_rel else None
            return market_data
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )
