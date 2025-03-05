from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from src.data_models.states_model import States
from src.data_models.districts_model import Districts
from datetime import datetime

class LocationService:
    def get_states(self, db:Session):
        try:
            states_data = db.query(States).all()
            if not states_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="States not found"
                )
            return states_data
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )

    def get_districts(self, id, db:Session):
        try:
            districts_data = db.query(Districts).filter(Districts.state_id==id).all()
            if not districts_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Districts not found for that state id"
                )
            return districts_data
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )

