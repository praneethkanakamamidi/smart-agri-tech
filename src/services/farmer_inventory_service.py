from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from src.data_models.crops_model import Crops
from src.data_models.soil_model import Soil
from src.data_models.fertilizers_model import Fertilizers
from src.data_models.farmer_inventory_model import FarmerInventory


class FarmerInventoryService:
    async def post_stock(self, payload, db: AsyncSession):
        try:
            new_stock = FarmerInventory(
                crop=payload.crop,
                fertilizer=payload.fertilizer,
                soil=payload.soil,
                weight_kg=payload.weight_kg,
                proposed_cost=payload.proposed_cost,
                description=payload.description,
                created_by=payload.created_by,
                created_at=datetime.now(),
            )
            db.add(new_stock)
            await db.commit()
            return {"success": "Record has been added"}
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def get_stock(self, id: int, db: AsyncSession):
        try:
            stmt = (
                select(FarmerInventory)
                .where(FarmerInventory.id == id)
                .options(
                    joinedload(FarmerInventory.crop_rel),
                    joinedload(FarmerInventory.soil_rel),
                    joinedload(FarmerInventory.fertilizer_rel),
                )
            )
            result = await db.execute(stmt)
            stock_data = result.scalar_one_or_none()
            if stock_data:
                stock_data.crop_data = stock_data.crop_rel.crop_name if stock_data.crop_rel else None
                stock_data.soil_name = stock_data.soil_rel.soil_name if stock_data.soil_rel else None
                stock_data.fertilizer_data = stock_data.fertilizer_rel.fertilizer_name if stock_data.fertilizer_rel else None
                return stock_data
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Error: There is no stock of that ID",
            )
        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def get_stocks(self, user_id: int, db: AsyncSession):
        try:
            stmt = (
                select(FarmerInventory)
                .where(FarmerInventory.created_by == user_id)
                .options(
                    joinedload(FarmerInventory.crop_rel),
                    joinedload(FarmerInventory.soil_rel),
                    joinedload(FarmerInventory.fertilizer_rel),
                )
            )
            result = await db.execute(stmt)
            stock_data = result.scalars().unique().all()
            if stock_data:
                for stock in stock_data:
                    stock.crop_name = stock.crop_rel.crop_name if stock.crop_rel else None
                    stock.soil_name = stock.soil_rel.soil_name if stock.soil_rel else None
                    stock.fertilizer_name = stock.fertilizer_rel.fertilizer_name if stock.fertilizer_rel else None
                return stock_data
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Error: There are no stocks in database",
            )
        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def put_stock(self, payload, db: AsyncSession):
        try:
            stmt = select(FarmerInventory).where(FarmerInventory.id == payload.id)
            result = await db.execute(stmt)
            existing_stock = result.scalar_one_or_none()
            if not existing_stock:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Error: There are no stock with that id in database",
                )
            existing_stock.crop = payload.crop
            existing_stock.fertilizer = payload.fertilizer
            existing_stock.soil = payload.soil
            existing_stock.weight_kg = payload.weight_kg
            existing_stock.proposed_cost = payload.proposed_cost
            existing_stock.description = payload.description
            existing_stock.updated_by = payload.updated_by
            existing_stock.updated_at = datetime.now()
            await db.commit()
            return {"success": "stock has been updated"}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def delete_stock(self, id: int, db: AsyncSession):
        try:
            stmt = select(FarmerInventory).where(FarmerInventory.id == id)
            result = await db.execute(stmt)
            stock_data = result.scalar_one_or_none()
            if not stock_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Error: There are no stock with that id in database",
                )
            await db.delete(stock_data)
            await db.commit()
            return {"success": "Stock record has been deleted successfully"}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )
