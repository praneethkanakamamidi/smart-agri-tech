from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from src.data_models.soil_model import Soil
from src.data_models.users_model import Users
from src.data_models.miscellaneous_model import Miscellaneous_Data
from datetime import datetime

class SoilService:
    def post_soil(self, payload, db:Session):
        try:
            existing_soil_data = db.query(Soil).filter(
                func.lower(Soil.soil_name)==payload.soil_name.lower()
                ).first()
            active_misc_data = db.query(Miscellaneous_Data).filter(
                Miscellaneous_Data.category == "status",
                Miscellaneous_Data.value == "active"
            ).first()

            if existing_soil_data:
                 raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Error: Soil of that name already exists",
                )
                 
            new_soil = Soil(
                soil_name=payload.soil_name,
                soil_texture=payload.soil_texture,
                description=payload.description,
                created_by=payload.created_by,
                status=active_misc_data.id,
                created_at=datetime.now()
            )
            db.add(new_soil)
            db.commit()
            
            return {"message": f"Soil '{payload.soil_name}' has been successfully created!"}
        
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )

        
    def get_soil(self, id, db: Session) -> list:
        try:
            soil_data = db.query(Soil).filter(Soil.id==id).first()
            created_user_data = db.query(Users).filter(Users.id==soil_data.created_by).first()
            updated_user_data = db.query(Users).filter(Users.id==soil_data.updated_by).first()
            status_data = db.query(Miscellaneous_Data).filter(Miscellaneous_Data.id ==soil_data.status).first()
            soil_data.created_user=created_user_data.first_name if created_user_data else None
            soil_data.updated_user=updated_user_data.first_name if updated_user_data else None
            soil_data.status_value=status_data.value if status_data else None
            return soil_data
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )
    
    def get_soil(self, db: Session) -> list:
        try:
            soil_data = db.query(Soil).order_by(Soil.created_at.desc()).all()
            for soil in soil_data:
                status_data = db.query(Miscellaneous_Data).filter(Miscellaneous_Data.id ==soil.status).first()
                soil.status_value=status_data.value if status_data else None
            return soil_data
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )

    def put_soil(self, payload, db:Session):
        try:
            existing_soil_data = db.query(Soil).filter(
                Soil.id==payload.id
                ).first()
            if not existing_soil_data:
                 raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Error: Soil of that id does not exist",
                )

            existing_soil_data.soil_name=payload.soil_name
            existing_soil_data.soil_texture=payload.soil_texture
            existing_soil_data.description=payload.description
            existing_soil_data.updated_by=payload.updated_by
            existing_soil_data.updated_at=datetime.now()
            db.commit()

            return  {"message": f"Soil has been updated"}
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )
            
    def soil_status(self, payload, db:Session):
        try:
            initial_state = ""
            final_state = ""

            existing_soil_data = db.query(Soil).filter(
                Soil.id==payload.id
                ).first()
            inactive_misc_data = db.query(Miscellaneous_Data).filter(
                Miscellaneous_Data.category == "status",
                Miscellaneous_Data.value == "inactive"

            ).first()
            active_misc_data = db.query(Miscellaneous_Data).filter(
                Miscellaneous_Data.category == "status",
                Miscellaneous_Data.value == "active"
            ).first()

            if not existing_soil_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Soil not found"
                )
            
            if not inactive_misc_data or not active_misc_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Status data not found"
                )

            if existing_soil_data.status == inactive_misc_data.id:
                existing_soil_data.status = active_misc_data.id
                existing_soil_data.updated_by=payload.updated_by
                existing_soil_data.updated_at=datetime.now()
                db.commit()
                initial_state = "inactive"
                final_state = "active"
                
            elif existing_soil_data.status == active_misc_data.id:
                existing_soil_data.status = inactive_misc_data.id
                existing_soil_data.updated_by=payload.updated_by
                existing_soil_data.updated_at=datetime.now()
                db.commit()
                initial_state = "active"
                final_state = "inactive"
            
            return {"message": f"{existing_soil_data.soil_name} status has been changed from {initial_state} to {final_state}"}

        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )


