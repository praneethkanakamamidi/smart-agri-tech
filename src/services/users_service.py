from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
from datetime import datetime, timedelta
import os

from src.data_models.users_model import Users
from src.data_models.roles_model import Roles
from src.security_utils.hashing_config import Hashing
from src.helpers.smtp_config import SmtpService
from src.data_models.miscellaneous_model import Miscellaneous_Data
from src.db_connections.mongo_conn import get_mongo_client


hashing = Hashing()
smtp_service = SmtpService()
MONGO_DB = os.getenv("MONGO_DB")
client = get_mongo_client()
database = client[MONGO_DB]
otp_collection = database["otps"]


class UsersService:
    async def add_user(self, payload, db: AsyncSession):
        try:
            stmt = select(Users).where(Users.user_name == payload.user_name)
            result = await db.execute(stmt)
            existing_user = result.scalar_one_or_none()
            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="User already exists"
                )

            stmt_misc = select(Miscellaneous_Data).where(
                Miscellaneous_Data.category == "status",
                Miscellaneous_Data.value == "inactive",
            )
            res_misc = await db.execute(stmt_misc)
            inactive_misc_data = res_misc.scalar_one_or_none()

            hashed_password = hashing.get_password_hash(payload.password.get_secret_value())
            otp = smtp_service.generate_secure_otp()
            otp_expiry = datetime.utcnow() + timedelta(minutes=10)

            await otp_collection.insert_one(
                {
                    "user_name": payload.user_name,
                    "otp": otp,
                    "expires_at": otp_expiry,
                    "attempts": 3,
                }
            )

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
            await db.commit()
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
            )

    async def verify_user_otp(self, payload, db: AsyncSession):
        try:
            otp_record = await otp_collection.find_one({"user_name": payload.user_name})
            if not otp_record:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="OTP not found"
                )

            otp_expiry = otp_record["expires_at"]
            current_time = datetime.utcnow()
            if current_time > otp_expiry:
                await otp_collection.delete_one({"user_name": payload.user_name})
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="OTP expired"
                )

            stored_otp = otp_record["otp"]
            entered_otp = payload.otp.get_secret_value()
            attempts_left = otp_record["attempts"]

            if stored_otp != entered_otp:
                if attempts_left > 1:
                    await otp_collection.update_one(
                        {"user_name": payload.user_name},
                        {"$inc": {"attempts": -1}},
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid OTP. {attempts_left - 1} attempts left.",
                    )
                else:
                    await otp_collection.delete_one({"user_name": payload.user_name})
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Maximum attempts reached. OTP expired.",
                    )

            await otp_collection.delete_one({"user_name": payload.user_name})

            stmt = select(Users).where(Users.user_name == payload.user_name)
            result = await db.execute(stmt)
            existing_user = result.scalar_one_or_none()
            if not existing_user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
                )

            stmt_active = select(Miscellaneous_Data).where(
                Miscellaneous_Data.category == "status",
                Miscellaneous_Data.value == "active",
            )
            res_active = await db.execute(stmt_active)
            active_misc_data = res_active.scalar_one_or_none()
            existing_user.status = active_misc_data.id
            await db.commit()
            return {"success": "OTP verified successfully"}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
            )

    async def get_user(self, id: int, db: AsyncSession):
        try:
            stmt = (
                select(Users)
                .where(Users.id == id)
                .options(
                    joinedload(Users.role_rel),
                    joinedload(Users.status_rel),
                )
            )
            result = await db.execute(stmt)
            user_data = result.scalar_one_or_none()
            if user_data:
                user_data.role_name = user_data.role_rel.name if user_data.role_rel else None
                user_data.user_status = user_data.status_rel.value if user_data.status_rel else None
                return user_data
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )
        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
            )

    async def get_all_users(self, db: AsyncSession):
        try:
            stmt = select(Users).order_by(Users.created_time.desc())
            result = await db.execute(stmt)
            users_data = result.scalars().all()
            if users_data:
                for user_data in users_data:
                    stmt_role = select(Roles).where(Roles.id == user_data.role_id)
                    res_role = await db.execute(stmt_role)
                    role_data = res_role.scalar_one_or_none()
                    user_data.role_name = role_data.name if role_data else None
                    stmt_misc = select(Miscellaneous_Data).where(
                        Miscellaneous_Data.id == user_data.status
                    )
                    res_misc = await db.execute(stmt_misc)
                    misc_data = res_misc.scalar_one_or_none()
                    user_data.user_status = misc_data.value if misc_data else None
                return users_data
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="No users found"
            )
        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
            )

    async def activate_deactivate_user(self, id: int, db: AsyncSession):
        try:
            stmt = select(Users).where(Users.id == id)
            result = await db.execute(stmt)
            user_data = result.scalar_one_or_none()

            stmt_inactive = select(Miscellaneous_Data).where(
                Miscellaneous_Data.category == "status",
                Miscellaneous_Data.value == "inactive",
            )
            stmt_active = select(Miscellaneous_Data).where(
                Miscellaneous_Data.category == "status",
                Miscellaneous_Data.value == "active",
            )
            res_inactive = await db.execute(stmt_inactive)
            res_active = await db.execute(stmt_active)
            inactive_misc_data = res_inactive.scalar_one_or_none()
            active_misc_data = res_active.scalar_one_or_none()

            if not user_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
                )
            if not inactive_misc_data or not active_misc_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Status data not found"
                )

            initial_state, final_state = "", ""
            if user_data.status == inactive_misc_data.id:
                user_data.status = active_misc_data.id
                await db.commit()
                initial_state, final_state = "inactive", "active"
            elif user_data.status == active_misc_data.id:
                user_data.status = inactive_misc_data.id
                await db.commit()
                initial_state, final_state = "active", "inactive"

            return {
                "message": f"User {user_data.user_name} status has been changed from {initial_state} to {final_state}"
            }
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
            )
