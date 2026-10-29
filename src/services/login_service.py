import os
import secrets
from datetime import timedelta, datetime, timezone

from fastapi import HTTPException, Depends, status, Request
from fastapi.security import OAuth2PasswordBearer
from jose import jwt
from sqlalchemy import select, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import totp
from src.core.audit import audit
from src.core.crypto import decrypt
from src.core.rate_limit import client_ip
from src.data_models.users_model import Users
from src.data_models.roles_model import Roles
from src.data_models.miscellaneous_model import Miscellaneous_Data
from src.data_models.platform_model import UserSessions
from src.security_utils.hashing_config import Hashing
from src.helpers.settings_config import OAuthSettings
from src.db_connections.database import get_db_async
from src.security_utils.oauth_config import OAuth2Handler
from src.services.permissions_service import PermissionsService
from src.core.clock import utcnow


hashing = Hashing()
oauth_settings = OAuthSettings()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login/")
permissions_service = PermissionsService()

MFA_TOKEN_MINUTES = 5
INVALID_CREDENTIALS = "Invalid login details."


def normalize_phone(value: str | None) -> str | None:
    """Store Indian mobile numbers as +91XXXXXXXXXX; leave other formats as typed (digits and +)."""
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit() or ch == "+")
    if digits.startswith("+"):
        return digits
    if len(digits) == 10:
        return "+91" + digits
    if len(digits) == 12 and digits.startswith("91"):
        return "+" + digits
    return digits


async def find_user_by_identifier(db: AsyncSession, identifier: str) -> Users | None:
    identifier = (identifier or "").strip()
    if not identifier:
        return None
    phone = normalize_phone(identifier) if not "@" in identifier else None
    conditions = [Users.user_name == identifier, Users.email == identifier.lower()]
    if phone:
        conditions.append(Users.phone == phone)
    rows = (await db.execute(select(Users).where(or_(*conditions), Users.deleted_at.is_(None)))).scalars().all()
    return rows[0] if len(rows) == 1 else (rows[0] if rows else None)


class LoginService(OAuth2Handler):
    def __init__(self):
        self.access_token_secret_key = oauth_settings.ACCESS_TOKEN
        self.refresh_token_secret_key = oauth_settings.REFRESH_TOKEN
        self.algorithm = oauth_settings.ALGORITHM
        self.access_expiry = timedelta(minutes=oauth_settings.ACCESS_EXPIRY)
        self.refresh_expiry = timedelta(minutes=oauth_settings.REFRESH_EXPIRY)

    # ---- token helpers -------------------------------------------------

    def _encode(self, claims: dict, secret: str, lifetime: timedelta) -> str:
        payload = dict(claims)
        # Aware UTC datetime: a naive utcnow().timestamp() is read as local time and skews `exp`.
        payload["exp"] = int((datetime.now(timezone.utc) + lifetime).timestamp())
        payload["iat"] = int(datetime.now(timezone.utc).timestamp())
        return jwt.encode(payload, secret, algorithm=self.algorithm)

    async def _issue_session(self, user: Users, db: AsyncSession, request: Request | None) -> dict:
        jti = secrets.token_hex(16)
        now = utcnow()
        db.add(UserSessions(
            user_id=user.id,
            jti=jti,
            device_name=(request.headers.get("x-device-name") if request else None),
            user_agent=(request.headers.get("user-agent", "")[:255] if request else None),
            ip_address=client_ip(request) if request else None,
            created_at=now,
            last_used_at=now,
            expires_at=now + self.refresh_expiry,
        ))
        user.last_login_at = now
        access_token = self._encode({"uid": user.user_name, "sid": jti, "typ": "access"},
                                    self.access_token_secret_key, self.access_expiry)
        refresh_token = self._encode({"uid": user.user_name, "sid": jti, "typ": "refresh"},
                                     self.refresh_token_secret_key, self.refresh_expiry)
        return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer", "session_id": jti}

    async def _login_response(self, user: Users, db: AsyncSession, request: Request | None) -> dict:
        tokens = await self._issue_session(user, db, request)
        permissions = await permissions_service.get_permissions(user.role_id, db)
        role_data = (await db.execute(select(Roles).where(Roles.id == user.role_id))).scalar_one_or_none()
        role_name = role_data.name.lower() if role_data else None
        audit(db, "auth.login", "user", user.id, actor_id=user.id, actor_role=role_name,
              ip_address=client_ip(request) if request else None)
        await db.commit()
        response = {
            "status": "success",
            "id": user.id,
            "user_name": user.user_name,
            "role": role_name,
            "verification_status": user.verification_status,
            "preferred_language": user.preferred_language,
            "permissions": permissions,
            **tokens,
        }
        if role_name == "admin" and not user.mfa_enabled:
            response["mfa_setup_recommended"] = True
        return response

    # ---- login flows ---------------------------------------------------

    async def login(self, form_data, db: AsyncSession, request: Request | None = None):
        user_data = await find_user_by_identifier(db, form_data.username)
        if not user_data or not user_data.password or not hashing.verify_password(form_data.password, user_data.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=INVALID_CREDENTIALS,
                headers={"WWW-Authenticate": "Bearer"},
            )

        status_value = await self._status_value(user_data, db)
        if status_value != "active":
            if status_value == "inactive" and user_data.suspended_reason == "self_deactivated":
                # Logging in again re-opens a self-deactivated account.
                user_data.status = await self._status_id(db, "active")
                user_data.suspended_reason = None
                audit(db, "account.reactivated", "user", user_data.id, actor_id=user_data.id)
            elif status_value == "suspended":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Your account is suspended. You can submit an appeal at /api/appeals.",
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: The user account is inactive. Verify your account or contact support.",
                )

        if user_data.mfa_enabled:
            mfa_token = self._encode({"uid": user_data.user_name, "typ": "mfa"},
                                     self.access_token_secret_key, timedelta(minutes=MFA_TOKEN_MINUTES))
            return {"status": "mfa_required", "mfa_required": True, "mfa_token": mfa_token}

        return await self._login_response(user_data, db, request)

    async def login_mfa(self, mfa_token: str, code: str, db: AsyncSession, request: Request | None = None):
        try:
            payload = jwt.decode(mfa_token, self.access_token_secret_key, algorithms=[self.algorithm])
        except jwt.JWTError:
            raise HTTPException(status_code=401, detail="MFA session expired. Log in again.")
        if payload.get("typ") != "mfa":
            raise HTTPException(status_code=401, detail="Invalid MFA token.")
        user = (await db.execute(select(Users).where(Users.user_name == payload.get("uid")))).scalar_one_or_none()
        if not user or not user.mfa_enabled:
            raise HTTPException(status_code=401, detail="Invalid MFA token.")
        secret = decrypt(user.mfa_secret_encrypted)
        if not secret or not totp.verify(secret, code):
            audit(db, "auth.mfa_failed", "user", user.id, actor_id=user.id,
                  ip_address=client_ip(request) if request else None)
            await db.commit()
            raise HTTPException(status_code=401, detail="Invalid authentication code.")
        return await self._login_response(user, db, request)

    async def refresh_access_token(self, refresh_token: str, db: AsyncSession, request: Request | None = None):
        """Rotate: the old refresh token's session is revoked and a new session is issued."""
        try:
            payload = jwt.decode(refresh_token, self.refresh_token_secret_key, algorithms=[self.algorithm])
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Refresh token has expired. Please log in again.")
        except jwt.JWTError:
            raise HTTPException(status_code=401, detail="Invalid refresh token.")

        user_data = (await db.execute(select(Users).where(Users.user_name == payload.get("uid")))).scalar_one_or_none()
        if not user_data or user_data.deleted_at:
            raise HTTPException(status_code=401, detail="User not found.")
        if await self._status_value(user_data, db) != "active":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: The user account is inactive.")

        sid = payload.get("sid")
        if sid:
            session = (await db.execute(select(UserSessions).where(UserSessions.jti == sid))).scalar_one_or_none()
            if not session or session.revoked_at:
                # Reuse of a rotated/revoked refresh token: revoke every session (possible token theft).
                await db.execute(update(UserSessions).where(
                    UserSessions.user_id == user_data.id, UserSessions.revoked_at.is_(None)
                ).values(revoked_at=utcnow()))
                audit(db, "auth.refresh_reuse_detected", "user", user_data.id, actor_id=user_data.id)
                await db.commit()
                raise HTTPException(status_code=401, detail="Session is no longer valid. Please log in again.")
            session.revoked_at = utcnow()

        tokens = await self._issue_session(user_data, db, request)
        await db.commit()
        return {"status": "success", **tokens}

    # ---- sessions --------------------------------------------------------

    async def logout(self, user: Users, session_id: str | None, all_devices: bool, db: AsyncSession):
        stmt = update(UserSessions).where(UserSessions.user_id == user.id, UserSessions.revoked_at.is_(None))
        if not all_devices:
            if not session_id:
                return {"success": "Logged out."}
            stmt = stmt.where(UserSessions.jti == session_id)
        await db.execute(stmt.values(revoked_at=utcnow()))
        audit(db, "auth.logout_all" if all_devices else "auth.logout", "user", user.id, actor_id=user.id)
        await db.commit()
        return {"success": "Logged out from all devices." if all_devices else "Logged out."}

    async def list_sessions(self, user: Users, current_sid: str | None, db: AsyncSession):
        rows = (await db.execute(
            select(UserSessions)
            .where(UserSessions.user_id == user.id, UserSessions.revoked_at.is_(None),
                   UserSessions.expires_at > utcnow())
            .order_by(UserSessions.last_used_at.desc())
        )).scalars().all()
        return [
            {
                "session_id": s.jti,
                "device_name": s.device_name,
                "user_agent": s.user_agent,
                "ip_address": s.ip_address,
                "created_at": s.created_at,
                "last_used_at": s.last_used_at,
                "expires_at": s.expires_at,
                "is_current": s.jti == current_sid,
            }
            for s in rows
        ]

    async def revoke_session(self, user: Users, session_id: str, db: AsyncSession):
        session = (await db.execute(select(UserSessions).where(
            UserSessions.jti == session_id, UserSessions.user_id == user.id
        ))).scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found.")
        session.revoked_at = utcnow()
        audit(db, "auth.session_revoked", "user_session", session.id, actor_id=user.id)
        await db.commit()
        return {"success": "Session revoked."}

    # ---- helpers -----------------------------------------------------------

    @staticmethod
    async def _status_id(db: AsyncSession, value: str) -> int:
        from src.core.lookups import misc_id

        return await misc_id(db, "status", value)

    @staticmethod
    async def _status_value(user_data: Users, db: AsyncSession) -> str | None:
        return (await db.execute(
            select(Miscellaneous_Data.value).where(Miscellaneous_Data.id == user_data.status)
        )).scalar_one_or_none()

    @staticmethod
    async def is_user_active(user_data: Users, db: AsyncSession) -> bool:
        return await LoginService._status_value(user_data, db) == "active"

    @staticmethod
    def decode_access_token(token: str) -> dict:
        try:
            payload = jwt.decode(token, oauth_settings.ACCESS_TOKEN, algorithms=[oauth_settings.ALGORITHM])
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=401,
                detail="Authentication failed: Token has expired. Please log in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except jwt.JWTError:
            raise HTTPException(
                status_code=401,
                detail="Authentication failed: Invalid token. Ensure you provide a valid authentication token.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if payload.get("typ") not in (None, "access"):
            raise HTTPException(status_code=401, detail="Authentication failed: Wrong token type.",
                                headers={"WWW-Authenticate": "Bearer"})
        return payload

    @staticmethod
    async def user_from_token(token: str, db: AsyncSession) -> Users:
        payload = LoginService.decode_access_token(token)
        username = payload.get("uid")
        if not username:
            raise HTTPException(
                status_code=401,
                detail="Authentication failed: Token is missing a valid user identifier.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user_data = (await db.execute(select(Users).where(Users.user_name == username))).scalar_one_or_none()
        if not user_data or user_data.deleted_at:
            raise HTTPException(
                status_code=401,
                detail="Authentication failed: User not found.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        sid = payload.get("sid")
        if sid:
            session = (await db.execute(select(UserSessions).where(UserSessions.jti == sid))).scalar_one_or_none()
            if not session or session.revoked_at:
                raise HTTPException(
                    status_code=401,
                    detail="Authentication failed: Session has been logged out.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            now = utcnow()
            if not session.last_used_at or (now - session.last_used_at) > timedelta(minutes=5):
                session.last_used_at = now
                await db.commit()

        status_value = await LoginService._status_value(user_data, db)
        if status_value != "active":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Your account is suspended." if status_value == "suspended"
                    else "Access denied: The user account is inactive. Contact support for assistance."
                ),
            )
        user_data.session_id = sid  # transient attribute for logout / session listing
        return user_data

    @staticmethod
    async def get_current_active_user(
        token: str = Depends(oauth2_scheme),
        db: AsyncSession = Depends(get_db_async),
    ):
        return await LoginService.user_from_token(token, db)


def admin_mfa_required() -> bool:
    return os.getenv("ADMIN_MFA_REQUIRED", "false").lower() == "true"
