from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from src.data_models.orders_model import Orders
from src.data_models.users_model import Users
from src.data_models.miscellaneous_model import Miscellaneous_Data
from datetime import datetime

class OrdersService:
    def post_order(self, payload, db:Session):
        try:
            return {"message": f"Order has been successfully placed"}
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )
        
    def get_vendor_orders(self, id, db: Session) -> list:
        try:
            return "true"
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )
    
    def get_farmer_orders(self, db: Session) -> list:
        try:
            return "fetched"
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )

    def order_status(self, payload, db:Session):
        try:
            return  {"message": f"order status has been changed"}
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )
            
