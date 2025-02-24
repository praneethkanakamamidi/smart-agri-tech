from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from src.data_models.crops_model import Crops
from src.data_models.users_model import Users
from src.data_models.miscellaneous_model import Miscellaneous_Data
from datetime import datetime

class CropService:
    def post_crop(self, payload, db:Session):
        try:
            existing_crop_data = db.query(Crops).filter(
                func.lower(Crops.crop_name)==payload.crop_name.lower()
                ).first()
            active_misc_data = db.query(Miscellaneous_Data).filter(
                Miscellaneous_Data.category == "status",
                Miscellaneous_Data.value == "active"
            ).first()

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
                created_at=datetime.now()
            )
            db.add(new_crop)
            db.commit()
            
            return {"message": f"Crop '{payload.crop_name}' has been successfully created!"}
        
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )

        
    def get_crop(self, id, db: Session) -> list:
        try:
            crop_data = db.query(Crops).filter(Crops.id==id).first()
            created_user_data = db.query(Users).filter(Users.id==crop_data.created_by).first()
            updated_user_data = db.query(Users).filter(Users.id==crop_data.updated_by).first()
            status_data = db.query(Miscellaneous_Data).filter(Miscellaneous_Data.id ==crop_data.status).first()
            crop_data.created_user=created_user_data.first_name if created_user_data else None
            crop_data.updated_user=updated_user_data.first_name if updated_user_data else None
            crop_data.status_value=status_data.value if status_data else None
            return crop_data
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )
    
    def get_crops(self, db: Session) -> list:
        try:
            crop_data = db.query(Crops).order_by(Crops.created_at.desc()).all()
            for crop in crop_data:
                status_data = db.query(Miscellaneous_Data).filter(Miscellaneous_Data.id ==crop.status).first()
                crop.status_value=status_data.value if status_data else None
            return crop_data
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )

    def put_crop(self, payload, db:Session):
        try:
            existing_crop_data = db.query(Crops).filter(
                Crops.id==payload.id
                ).first()
            if not existing_crop_data:
                 raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Error: Crop of that id does not exist",
                )

            existing_crop_data.crop_name=payload.crop_name
            existing_crop_data.crop_type=payload.crop_type
            existing_crop_data.description=payload.description
            existing_crop_data.updated_by=payload.updated_by
            existing_crop_data.updated_at=datetime.now()
            db.commit()

            return  {"message": f"Crop has been updated"}
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )
            
    def crop_status(self, payload, db:Session):
        try:
            initial_state = ""
            final_state = ""

            existing_crop_data = db.query(Crops).filter(
                Crops.id==payload.id
                ).first()
            inactive_misc_data = db.query(Miscellaneous_Data).filter(
                Miscellaneous_Data.category == "status",
                Miscellaneous_Data.value == "inactive"

            ).first()
            active_misc_data = db.query(Miscellaneous_Data).filter(
                Miscellaneous_Data.category == "status",
                Miscellaneous_Data.value == "active"
            ).first()

            if not existing_crop_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Crop not found"
                )
            
            if not inactive_misc_data or not active_misc_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Status data not found"
                )

            if existing_crop_data.status == inactive_misc_data.id:
                existing_crop_data.status = active_misc_data.id
                existing_crop_data.updated_by=payload.updated_by
                existing_crop_data.updated_at=datetime.now()
                db.commit()
                initial_state = "inactive"
                final_state = "active"
                
            elif existing_crop_data.status == active_misc_data.id:
                existing_crop_data.status = inactive_misc_data.id
                existing_crop_data.updated_by=payload.updated_by
                existing_crop_data.updated_at=datetime.now()
                db.commit()
                initial_state = "active"
                final_state = "inactive"
            
            return {"message": f"{existing_crop_data.crop_name} status has been changed from {initial_state} to {final_state}"}

        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )


