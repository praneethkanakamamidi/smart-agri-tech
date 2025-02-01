from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from src.data_models.miscellaneous_model import Miscellaneous_Data

class MiscellaneousDataService:
    def get_miscellaneous_data(self, id: int, db: Session):
        try:
            miscellaneous_data_values = db.query(Miscellaneous_Data).filter(Miscellaneous_Data.id == id).first()
            if not miscellaneous_data_values:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Miscellaneous data not found"
                )
            return miscellaneous_data_values
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e),
                headers={"Content-Type": "application/json"}
            )
