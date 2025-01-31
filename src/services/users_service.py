from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException, status
from src.data_models.users_model import Users
from src.security_utils.hashing_config import Hashing

hashing = Hashing()

class UsersService:
    def add_user(self, payload, db: Session):
        try:
            hashed_password = hashing.get_password_hash(payload.password)
            new_user = Users(
                user_name=payload.user_name,
                first_name=payload.first_name,
                last_name=payload.last_name,
                password=hashed_password,
                role_id=payload.role_id,
                created_by=payload.created_by
            )
            db.add(new_user)
            db.commit()
            return {"success": "New user has been created"}
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )
        finally:
            db.close()

    def get_user(self, id: int, db: Session):
        try:
            user_data = db.query(Users).filter(Users.id == id).one_or_none()
            if user_data:
                return user_data
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )
        finally:
            db.close()
