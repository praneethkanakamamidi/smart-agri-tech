from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from src.data_models.crops_model import Crops
from src.data_models.soil_model import Soil
from src.data_models.fertilizers_model import Fertilizers
from src.data_models.farmer_inventory_model import FarmerInventory
from src.data_models.users_model import Users
from src.data_models.miscellaneous_model import Miscellaneous_Data
from datetime import datetime

class FarmerInventoryService:
    def post_stock(self, payload, db:Session):
        try:
            new_stock = FarmerInventory(
                crop=payload.crop,
                fertilizer=payload.fertilizer,
                soil=payload.soil,
                weight_kg=payload.weight_kg,
                proposed_cost=payload.proposed_cost,
                description=payload.description,
                created_by=payload.created_by,
                created_at=datetime.now()
            )
            db.add(new_stock)
            db.commit()
            return {"success":"Record has been added"}
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )

    def get_stock(self, id, db: Session):
        try:
            stock_data = db.query(FarmerInventory).filter(FarmerInventory.id==id).first()
            if stock_data:
                crop_data = db.query(Crops).filter(Crops.id==stock_data.crop).first()
                soil_data = db.query(Soil).filter(Soil.id==stock_data.soil).first()
                fertilizer_data = db.query(Fertilizers).filter(Fertilizers.id==stock_data.fertilizer).first()
                stock_data.crop_data = crop_data.crop_name if crop_data else None
                stock_data.soil_name = soil_data.soil_name if soil_data else None
                stock_data.fertilizer_data = fertilizer_data.fertilizer_name if fertilizer_data else None
                return stock_data
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Error: There is no stock of that ID",
                )
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )

    def get_stocks(self, user_id, db: Session):
        try:
            stock_data = db.query(FarmerInventory).filter(FarmerInventory.created_by==user_id).all()
            if stock_data:
                for stock in stock_data:
                    crop_data = db.query(Crops).filter(Crops.id==stock.crop).first()
                    soil_data = db.query(Soil).filter(Soil.id==stock.soil).first()
                    fertilizer_data = db.query(Fertilizers).filter(Fertilizers.id==stock.fertilizer).first()
                    stock.crop_name = crop_data.crop_name if crop_data else None
                    stock.soil_name = soil_data.soil_name if soil_data else None
                    stock.fertilizer_name = fertilizer_data.fertilizer_name if fertilizer_data else None
                return stock_data
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Error: There are no stocks in database",
                )
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )
    
    def put_stock(self, payload, db:Session):
        try:
            existing_stock = db.query(FarmerInventory).filter(FarmerInventory.id==payload.id).first()
            if not existing_stock:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Error: There are no stock with that id in database",
                )
            existing_stock.crop=payload.crop
            existing_stock.fertilizer=payload.fertilizer
            existing_stock.soil=payload.soil
            existing_stock.weight_kg=payload.weight_kg
            existing_stock.proposed_cost=payload.proposed_cost
            existing_stock.description=payload.description
            existing_stock.updated_by=payload.updated_by
            existing_stock.updated_at=datetime.now()
            db.commit()
            db.refresh(existing_stock)  
            return{"sucess":"stock has been updated"}

        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )
    
    def delete_stock(self, id, db:Session):
        try:
            stock_data = db.query(FarmerInventory).filter(FarmerInventory.id==id).first()
            if not stock_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Error: There are no stock with that id in database",
                )
            db.delete(stock_data)
            db.commit()
            return {"success":"Stock record has been deleted successfully"}
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )
