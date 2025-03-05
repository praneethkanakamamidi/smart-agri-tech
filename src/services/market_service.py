from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from src.data_models.farmer_inventory_model import FarmerInventory
from src.data_models.users_model import Users
from src.data_models.states_model import States
from src.data_models.districts_model import Districts
from datetime import datetime

class MarketService:
    def get_market(self, db: Session) -> list:
        try:
            market_data = db.query(FarmerInventory).all()
            for data in market_data:
                user_details = db.query(Users).filter(
                    Users.id==data.created_by
                    ).first()
                user_state = db.query(States).filter(
                    States.id==user_details.state
                    ).first()
                user_district = db.query(Districts).filter(
                    States.id==user_details.district
                    ).first()
                data.farmer_name = user_details.first_name + user_details.last_name if user_details else None
                data.state = user_state.state_name if user_state else None
                data.district = user_district.district_name if user_district else None
            return market_data
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )