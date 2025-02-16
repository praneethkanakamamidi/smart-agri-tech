from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from datetime import datetime, timedelta
from src.data_models.users_model import Users
from src.data_models.roles_model import Roles
from src.security_utils.hashing_config import Hashing
from src.helpers.smtp_config import SmtpService
from src.data_models.miscellaneous_model import Miscellaneous_Data
from src.db_connections.mongo_conn import get_mongo_client
import os


hashing = Hashing()
smtp_service = SmtpService()

MONGO_DB = os.getenv("MONGO_DB")
client = get_mongo_client()
database = client[MONGO_DB]
otp_collection = database["otps"]  # Reference the correct collection

class UsersService:
    async def add_user(self, payload, db: Session):
        try:
            existing_user = db.query(Users).filter(Users.user_name == payload.user_name).first()
            if existing_user:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already exists")

            inactive_misc_data = db.query(Miscellaneous_Data).filter(
                Miscellaneous_Data.category == "status",
                Miscellaneous_Data.value == "inactive"
            ).first()
            
            hashed_password = hashing.get_password_hash(payload.password.get_secret_value())

            otp = smtp_service.generate_secure_otp()
            otp_expiry = datetime.utcnow() + timedelta(minutes=10)

            # Insert OTP with 3 attempts in MongoDB
            await otp_collection.insert_one({
                "user_name": payload.user_name,
                "otp": otp,
                "expires_at": otp_expiry,
                "attempts": 3  # New field to track attempts
            })

            new_user = Users(
                user_name=payload.user_name,
                first_name=payload.first_name,
                last_name=payload.last_name,
                password=hashed_password,
                role_id=payload.role_id,
                status=inactive_misc_data.id,
            )

            subject = "Your OTP for Account Verification"
            message = f"Hello {payload.first_name},\n\nYour OTP for account verification is: {otp}\n\nRegards,\nSmart Agri Tech"
            smtp_service.send_email_alert(payload.user_name, subject, message)
            db.add(new_user)
            db.commit()
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
        finally:
            db.close()

    async def verify_user_otp(self, payload, db: Session):
        try:
            otp_record = await otp_collection.find_one({"user_name": payload.user_name})

            if not otp_record:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OTP not found")

            otp_expiry = otp_record["expires_at"]
            current_time = datetime.utcnow()

            if current_time > otp_expiry:
                await otp_collection.delete_one({"user_name": payload.user_name})
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTP expired")

            stored_otp = otp_record["otp"]
            entered_otp = payload.otp.get_secret_value()
            attempts_left = otp_record["attempts"]

            if stored_otp != entered_otp:
                if attempts_left > 1:
                    await otp_collection.update_one(
                        {"user_name": payload.user_name},
                        {"$inc": {"attempts": -1}}
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid OTP. {attempts_left - 1} attempts left."
                    )
                else:
                    await otp_collection.delete_one({"user_name": payload.user_name})
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Maximum attempts reached. OTP expired.")

            await otp_collection.delete_one({"user_name": payload.user_name})
            existing_user = db.query(Users).filter(Users.user_name == payload.user_name).first()
            active_misc_data = db.query(Miscellaneous_Data).filter(
                Miscellaneous_Data.category == "status",
                Miscellaneous_Data.value == "active"
            ).first()
            existing_user.status=active_misc_data.id
            return {"success": "OTP verified successfully"}
            
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    
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
    
    def get_all_users(self, db: Session):
        try:
            users_data = db.query(Users).order_by(Users.created_time.desc()).all()
            if users_data:
                return users_data
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No users found"
            )
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )
        finally:
            db.close()

