from fastapi import HTTPException, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt
from datetime import timedelta, datetime

from src.data_models.users_model import Users
from src.data_models.roles_model import Roles
from src.data_models.miscellaneous_model import Miscellaneous_Data
from src.security_utils.hashing_config import Hashing
from src.helpers.settings_config import OAuthSettings
from fastapi.security import OAuth2PasswordBearer
from src.db_connections.database import get_db_async
from src.security_utils.oauth_config import OAuth2Handler
from src.services.permissions_service import PermissionsService


hashing = Hashing()
oauth_settings = OAuthSettings()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")
permissions_service = PermissionsService()


class LoginService(OAuth2Handler):
    def __init__(self):
        self.access_token_secret_key = oauth_settings.ACCESS_TOKEN
        self.refresh_token_secret_key = oauth_settings.REFRESH_TOKEN
        self.algorithm = oauth_settings.ALGORITHM
        self.access_expiry = timedelta(minutes=oauth_settings.ACCESS_EXPIRY)
        self.refresh_expiry = timedelta(minutes=oauth_settings.REFRESH_EXPIRY)

    async def login(self, form_data, db: AsyncSession):
        stmt = select(Users).where(Users.user_name == form_data.username)
        result = await db.execute(stmt)
        user_data = result.scalar_one_or_none()
        if not user_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found: Enter valid user details",
                headers={"Content-Type": "application/json"},
            )

        if not hashing.verify_password(form_data.password, user_data.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed: The provided password is incorrect",
                headers={"Content-Type": "application/json"},
            )

        stmt_active = select(Miscellaneous_Data).where(
            Miscellaneous_Data.category == "status",
            Miscellaneous_Data.value == "active",
        )
        res_active = await db.execute(stmt_active)
        active_data = res_active.scalar_one_or_none()

        if user_data.status != active_data.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: The user account is inactive. Contact support for assistance.",
                headers={"Content-Type": "application/json"},
            )

        permissions = await permissions_service.get_permissions(user_data.role_id, db)

        stmt_role = select(Roles).where(Roles.id == user_data.role_id)
        res_role = await db.execute(stmt_role)
        role_data = res_role.scalar_one_or_none()

        access_token = self.generate_access_token(
            user_data, self.access_token_secret_key, self.access_expiry
        )
        refresh_token = self.generate_refresh_token(user_data, self.refresh_expiry)

        return {
            "status": "success",
            "id": user_data.id,
            "user_name": user_data.user_name,
            "role": role_data.name if role_data else None,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "permissions": permissions,
        }

    @staticmethod
    async def get_current_active_user(
        token: str = Depends(oauth2_scheme),
        db: AsyncSession = Depends(get_db_async),
    ):
        try:
            payload = jwt.decode(
                token,
                oauth_settings.ACCESS_TOKEN,
                algorithms=[oauth_settings.ALGORITHM],
            )
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=401,
                detail="Authentication failed: Token has expired. Please log in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except jwt.InvalidTokenError:
            raise HTTPException(
                status_code=401,
                detail="Authentication failed: Invalid token. Ensure you provide a valid authentication token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        username = payload.get("uid")
        if not username:
            raise HTTPException(
                status_code=401,
                detail="Authentication failed: Token is missing a valid user identifier.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        stmt = select(Users).where(Users.user_name == username)
        result = await db.execute(stmt)
        user_data = result.scalar_one_or_none()
        if not user_data:
            raise HTTPException(
                status_code=401,
                detail=f"Authentication failed: User '{username}' not found in the system.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return user_data
