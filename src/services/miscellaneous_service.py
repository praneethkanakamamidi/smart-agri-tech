from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from src.db_connections.postgresql_conn import get_db
from src.data_models.miscellaneous_model import Miscellaneous_Data

class Miscellaneous_Data_Service:
    def get_miscellaneous_data(self, id):
        db=next(get_db())
        try:
            miscellaneous_data_values = db.query(Miscellaneous_Data).filter(Miscellaneous_Data.id == id).first()
            return miscellaneous_data_values
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e),
                headers={"Content-Type": "application/json"}
            ) 
        finally:
            db.close() 
    