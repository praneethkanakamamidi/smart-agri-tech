from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from src.data_models.fertilizers_model import Fertilizers
from src.data_models.users_model import Users
from src.data_models.miscellaneous_model import Miscellaneous_Data
from datetime import datetime

class FertilizersService:
    def post_fertilizer(self, payload, db:Session):
        try:
            existing_fertilizer_data = db.query(Fertilizers).filter(
                func.lower(Fertilizers.fetilizer_name)==payload.fetilizer_name.lower()
                ).first()
            active_misc_data = db.query(Miscellaneous_Data).filter(
                Miscellaneous_Data.category == "status",
                Miscellaneous_Data.value == "active"
            ).first()

            if existing_fertilizer_data:
                 raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Error: Fertilizer of that name already exists",
                )
                 
            new_fertilizer = Fertilizers(
                fetilizer_name=payload.fetilizer_name,
                application_method=payload.application_method,
                description=payload.description,
                created_by=payload.created_by,
                status=active_misc_data.id,
                created_at=datetime.now()
            )
            db.add(new_fertilizer)
            db.commit()
            
            return {"message": f"Fertilizer '{payload.fetilizer_name}' has been successfully created!"}
        
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )

        
    def get_fertilizer(self, id, db: Session) -> list:
        try:
            fertilizer_data = db.query(Fertilizers).filter(Fertilizers.id==id).first()
            created_user_data = db.query(Users).filter(Users.id==fertilizer_data.created_by).first()
            updated_user_data = db.query(Users).filter(Users.id==fertilizer_data.updated_by).first()
            status_data = db.query(Miscellaneous_Data).filter(Miscellaneous_Data.id ==fertilizer_data.id).first()
            fertilizer_data.created_user=created_user_data.first_name if created_user_data else None
            fertilizer_data.updated_user=updated_user_data.first_name if updated_user_data else None
            fertilizer_data.fertilizer_status=status_data.value if status_data else None
            return fertilizer_data
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )
    
    def get_fertilizers(self, db: Session) -> list:
        try:
            fertilizer_data = db.query(Fertilizers).order_by(Fertilizers.created_at.desc()).all()
            for fertilizer in fertilizer_data:
                status_data = db.query(Miscellaneous_Data).filter(Miscellaneous_Data.id ==fertilizer.status).first()
                fertilizer.fertilizer_status=status_data.value if status_data else None
            return fertilizer_data
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )

    def put_fertilizer(self, payload, db:Session):
        try:
            existing_fertilizer_data = db.query(Fertilizers).filter(
                Fertilizers.id==payload.id
                ).first()
            if not existing_fertilizer_data:
                 raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Error: Fertilizer of that id does not exist",
                )

            existing_fertilizer_data.fetilizer_name=payload.fetilizer_name
            existing_fertilizer_data.application_method=payload.application_method
            existing_fertilizer_data.description=payload.description
            existing_fertilizer_data.updated_by=payload.updated_by
            existing_fertilizer_data.updated_at=datetime.now()
            db.commit()

            return  {"message": f"Fertilizer has been updated"}
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )
            
    def fertilizer_status(self, payload, db:Session):
        try:
            initial_state = ""
            final_state = ""

            existing_fertilizer_data = db.query(Fertilizers).filter(
                Fertilizers.id==payload.id
                ).first()
            inactive_misc_data = db.query(Miscellaneous_Data).filter(
                Miscellaneous_Data.category == "status",
                Miscellaneous_Data.value == "inactive"

            ).first()
            active_misc_data = db.query(Miscellaneous_Data).filter(
                Miscellaneous_Data.category == "status",
                Miscellaneous_Data.value == "active"
            ).first()

            if not existing_fertilizer_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Fertilizer not found"
                )
            
            if not inactive_misc_data or not active_misc_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Status data not found"
                )

            if existing_fertilizer_data.status == inactive_misc_data.id:
                existing_fertilizer_data.status = active_misc_data.id
                existing_fertilizer_data.updated_by=payload.updated_by
                existing_fertilizer_data.updated_at=datetime.now()
                db.commit()
                initial_state = "inactive"
                final_state = "active"
                
            elif existing_fertilizer_data.status == active_misc_data.id:
                existing_fertilizer_data.status = inactive_misc_data.id
                db.commit()
                existing_fertilizer_data.updated_by=payload.updated_by
                existing_fertilizer_data.updated_at=datetime.now()
                initial_state = "active"
                final_state = "inactive"
            
            return {"message": f"{existing_fertilizer_data.fetilizer_name} status has been changed from {initial_state} to {final_state}"}

        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )


