import re
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select, or_, update
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import otp, totp
from src.core.audit import audit
from src.core.crypto import encrypt, decrypt
from src.core.i18n import normalize_language
from src.core.lookups import misc_id
from src.data_models.users_model import Users, SUSPENDED
from src.data_models.roles_model import Roles
from src.data_models.districts_model import Districts
from src.data_models.miscellaneous_model import Miscellaneous_Data
from src.data_models.platform_model import UserSessions, AccountAppeals
from src.security_utils.hashing_config import Hashing
from src.services.login_service import normalize_phone, find_user_by_identifier
from src.services.notifications_service import notify_user
from src.data_models.notifications_model import SECURITY

hashing = Hashing()
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_password(password: str):
    if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 8 characters and contain letters and numbers.",
        )


def _otp_target(identifier: str) -> tuple[str, str, str]:
    """(purpose, channel, address) for a verification code sent to an email or phone."""
    if "@" in identifier:
        return "verify_email", "email", identifier.lower()
    phone = normalize_phone(identifier)
    return "verify_phone", "sms", phone


class UsersService:
    # ---- registration & verification ---------------------------------------

    async def add_user(self, payload, db: AsyncSession):
        email = (payload.email or (payload.user_name if payload.user_name and "@" in payload.user_name else None))
        email = email.strip().lower() if email else None
        phone = normalize_phone(payload.phone or (payload.user_name if payload.user_name and "@" not in payload.user_name else None))
        if not email and not phone:
            raise HTTPException(status_code=422, detail="Provide a mobile number or an email address.")
        if email and not EMAIL_RE.match(email):
            raise HTTPException(status_code=422, detail="Enter a valid email address.")
        if phone and not re.fullmatch(r"\+\d{10,15}", phone):
            raise HTTPException(status_code=422, detail="Enter a valid mobile number.")
        password = payload.password.get_secret_value()
        validate_password(password)

        conditions = []
        if email:
            conditions += [Users.email == email, Users.user_name == email]
        if phone:
            conditions += [Users.phone == phone, Users.user_name == phone]
        if (await db.execute(select(Users.id).where(or_(*conditions)))).first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already exists")

        if payload.role:
            role_data = (await db.execute(select(Roles).where(Roles.name.ilike(payload.role)))).scalar_one_or_none()
        else:
            role_data = (await db.execute(select(Roles).where(Roles.id == payload.role_id))).scalar_one_or_none()
        if not role_data or role_data.name.lower() not in ("farmer", "vendor"):
            raise HTTPException(status_code=422, detail="Choose Farmer or Vendor as the account role.")

        if payload.district is not None:
            await self._validate_location(payload.state, payload.district, db)

        new_user = Users(
            user_name=email or phone,
            email=email,
            phone=phone,
            first_name=payload.first_name,
            last_name=payload.last_name,
            password=hashing.get_password_hash(password),
            role_id=role_data.id,
            state=payload.state,
            district=payload.district,
            status=await misc_id(db, "status", "inactive"),
            preferred_language=normalize_language(payload.preferred_language),
            verification_status="UNVERIFIED",
            created_time=datetime.utcnow(),
        )
        db.add(new_user)
        await db.flush()

        debug_codes = {}
        if phone:
            code = await otp.issue(db, phone, "verify_phone", "sms", phone)
            if code:
                debug_codes["phone"] = code
        if email:
            code = await otp.issue(db, email, "verify_email", "email", email)
            if code:
                debug_codes["email"] = code
        audit(db, "account.registered", "user", new_user.id, actor_id=new_user.id, actor_role=role_data.name.lower())
        await db.commit()
        response = {
            "success": "User registered. Enter the verification code we sent to activate your account.",
            "user_id": new_user.id,
            "verification_sent_to": [x for x in (phone, email) if x],
        }
        if debug_codes:
            response["debug_otp"] = debug_codes
        return response

    async def resend_otp(self, identifier: str, db: AsyncSession):
        user = await find_user_by_identifier(db, identifier)
        purpose, channel, address = _otp_target(identifier)
        response = {"success": "If the account exists and is unverified, a new code has been sent."}
        if user and ((purpose == "verify_email" and not user.email_verified and user.email == address)
                     or (purpose == "verify_phone" and not user.phone_verified and user.phone == address)):
            code = await otp.issue(db, address, purpose, channel, address)
            await db.commit()
            if code:
                response["debug_otp"] = code
        return response

    async def verify_user_otp(self, payload, db: AsyncSession):
        purpose, _, address = _otp_target(payload.user_name)
        user = await find_user_by_identifier(db, payload.user_name)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        await otp.verify(db, address, purpose, payload.otp.get_secret_value())

        if purpose == "verify_email":
            user.email_verified = True
        else:
            user.phone_verified = True
        inactive_id = await misc_id(db, "status", "inactive")
        if user.status == inactive_id and user.suspended_reason is None:
            user.status = await misc_id(db, "status", "active")
        audit(db, f"account.{purpose}", "user", user.id, actor_id=user.id)
        await db.commit()
        return {"success": "OTP verified successfully", "email_verified": user.email_verified,
                "phone_verified": user.phone_verified}

    # ---- contact details ---------------------------------------------------

    async def change_contact(self, user: Users, payload, db: AsyncSession):
        """Add or change email/phone; the new value is saved only after its code is verified."""
        if not payload.email and not payload.phone:
            raise HTTPException(status_code=422, detail="Provide an email or a mobile number.")
        sent = {}
        if payload.email:
            email = payload.email.strip().lower()
            if not EMAIL_RE.match(email):
                raise HTTPException(status_code=422, detail="Enter a valid email address.")
            if (await db.execute(select(Users.id).where(Users.email == email, Users.id != user.id))).first():
                raise HTTPException(status_code=409, detail="Email is already in use.")
            sent["email"] = await otp.issue(db, f"{user.id}:{email}", "verify_email", "email", email)
        if payload.phone:
            phone = normalize_phone(payload.phone)
            if (await db.execute(select(Users.id).where(Users.phone == phone, Users.id != user.id))).first():
                raise HTTPException(status_code=409, detail="Mobile number is already in use.")
            sent["phone"] = await otp.issue(db, f"{user.id}:{phone}", "verify_phone", "sms", phone)
        await db.commit()
        response = {"success": "Verification code sent."}
        debug = {k: v for k, v in sent.items() if v}
        if debug:
            response["debug_otp"] = debug
        return response

    async def verify_contact(self, user: Users, payload, db: AsyncSession):
        purpose, _, address = _otp_target(payload.identifier)
        await otp.verify(db, f"{user.id}:{address}", purpose, payload.otp.get_secret_value())
        before = {"email": user.email, "phone": user.phone}
        if purpose == "verify_email":
            user.email, user.email_verified = address, True
        else:
            user.phone, user.phone_verified = address, True
        audit(db, "account.contact_changed", "user", user.id, actor_id=user.id, before=before,
              after={"email": user.email, "phone": user.phone})
        await notify_user(db, user.id, "account_status", {"status": "updated", "reason": "Contact details changed."},
                          category=SECURITY)
        await db.commit()
        return {"success": "Contact details updated.", "email": user.email, "phone": user.phone}

    # ---- passwords ---------------------------------------------------------

    async def request_password_reset(self, identifier: str, db: AsyncSession):
        user = await find_user_by_identifier(db, identifier)
        response = {"success": "If an account exists for these details, a reset code has been sent."}
        if user:
            if "@" in identifier and user.email:
                code = await otp.issue(db, f"reset:{user.id}", "password_reset", "email", user.email)
            elif user.phone:
                code = await otp.issue(db, f"reset:{user.id}", "password_reset", "sms", user.phone)
            else:
                code = await otp.issue(db, f"reset:{user.id}", "password_reset", "email", user.email)
            await db.commit()
            if code:
                response["debug_otp"] = code
        return response

    async def confirm_password_reset(self, payload, db: AsyncSession):
        user = await find_user_by_identifier(db, payload.identifier)
        if not user:
            raise HTTPException(status_code=400, detail="Invalid or expired code.")
        await otp.verify(db, f"reset:{user.id}", "password_reset", payload.otp.get_secret_value())
        new_password = payload.new_password.get_secret_value()
        validate_password(new_password)
        user.password = hashing.get_password_hash(new_password)
        user.updated_time = datetime.utcnow()
        await self._revoke_all_sessions(user.id, db)
        audit(db, "account.password_reset", "user", user.id, actor_id=user.id)
        await notify_user(db, user.id, "account_status", {"status": "updated", "reason": "Your password was reset."},
                          category=SECURITY)
        await db.commit()
        return {"success": "Password updated. Please log in again on all devices."}

    async def change_password(self, user: Users, payload, db: AsyncSession):
        if not hashing.verify_password(payload.current_password.get_secret_value(), user.password):
            raise HTTPException(status_code=400, detail="Current password is incorrect.")
        new_password = payload.new_password.get_secret_value()
        validate_password(new_password)
        user.password = hashing.get_password_hash(new_password)
        user.updated_time = datetime.utcnow()
        await db.execute(update(UserSessions).where(
            UserSessions.user_id == user.id, UserSessions.revoked_at.is_(None),
            UserSessions.jti != (getattr(user, "session_id", None) or ""),
        ).values(revoked_at=datetime.utcnow()))
        audit(db, "account.password_changed", "user", user.id, actor_id=user.id)
        await notify_user(db, user.id, "account_status", {"status": "updated", "reason": "Your password was changed."},
                          category=SECURITY)
        await db.commit()
        return {"success": "Password changed. Other devices have been logged out."}

    # ---- deactivation / deletion / appeals -----------------------------------

    async def deactivate(self, user: Users, payload, db: AsyncSession):
        if not hashing.verify_password(payload.password.get_secret_value(), user.password):
            raise HTTPException(status_code=400, detail="Password is incorrect.")
        user.status = await misc_id(db, "status", "inactive")
        user.suspended_reason = "self_deactivated"
        await self._revoke_all_sessions(user.id, db)
        audit(db, "account.deactivated", "user", user.id, actor_id=user.id, after={"reason": payload.reason})
        await db.commit()
        return {"success": "Account deactivated. Log in again any time to reactivate it."}

    async def request_deletion(self, user: Users, payload, db: AsyncSession):
        if not hashing.verify_password(payload.password.get_secret_value(), user.password):
            raise HTTPException(status_code=400, detail="Password is incorrect.")
        from src.core.platform_settings import get_setting

        grace_days = await get_setting(db, "account_deletion_grace_days")
        user.deletion_requested_at = datetime.utcnow()
        audit(db, "account.deletion_requested", "user", user.id, actor_id=user.id, after={"reason": payload.reason})
        await db.commit()
        return {
            "success": f"Deletion requested. Your personal data will be anonymised after {grace_days} days. "
                       "Order and payment records are kept as required for accounting.",
            "cancel_with": "DELETE /api/users/me/deletion-request",
        }

    async def cancel_deletion(self, user: Users, db: AsyncSession):
        user.deletion_requested_at = None
        audit(db, "account.deletion_cancelled", "user", user.id, actor_id=user.id)
        await db.commit()
        return {"success": "Deletion request cancelled."}

    async def submit_appeal(self, payload, db: AsyncSession):
        """Suspended users can't log in, so they authenticate with their password here."""
        user = await find_user_by_identifier(db, payload.identifier)
        if not user or not hashing.verify_password(payload.password.get_secret_value(), user.password):
            raise HTTPException(status_code=401, detail="Invalid login details.")
        if user.verification_status != SUSPENDED and user.status != await misc_id(db, "status", "suspended"):
            raise HTTPException(status_code=400, detail="Only suspended accounts can submit an appeal.")
        existing = (await db.execute(select(AccountAppeals.id).where(
            AccountAppeals.user_id == user.id, AccountAppeals.status == "open"
        ))).first()
        if existing:
            raise HTTPException(status_code=409, detail="You already have an open appeal.")
        appeal = AccountAppeals(user_id=user.id, reason=payload.reason, status="open", created_at=datetime.utcnow())
        db.add(appeal)
        audit(db, "account.appeal_submitted", "user", user.id, actor_id=user.id)
        await db.commit()
        return {"success": "Appeal submitted. Our team will review it.", "appeal_id": appeal.id}

    # ---- MFA ---------------------------------------------------------------

    async def mfa_setup(self, user: Users, db: AsyncSession):
        if user.mfa_enabled:
            raise HTTPException(status_code=400, detail="MFA is already enabled.")
        secret = totp.generate_secret()
        user.mfa_secret_encrypted = encrypt(secret)
        await db.commit()
        return {
            "secret": secret,
            "otpauth_uri": totp.provisioning_uri(secret, user.user_name),
            "next_step": "Add this to an authenticator app, then POST /api/auth/mfa/enable with a current code.",
        }

    async def mfa_enable(self, user: Users, code: str, db: AsyncSession):
        secret = decrypt(user.mfa_secret_encrypted)
        if not secret:
            raise HTTPException(status_code=400, detail="Run MFA setup first.")
        if not totp.verify(secret, code):
            raise HTTPException(status_code=400, detail="Invalid authentication code.")
        user.mfa_enabled = True
        audit(db, "auth.mfa_enabled", "user", user.id, actor_id=user.id)
        await db.commit()
        return {"success": "Multi-factor authentication enabled."}

    async def mfa_disable(self, user: Users, code: str, db: AsyncSession):
        secret = decrypt(user.mfa_secret_encrypted)
        if not user.mfa_enabled or not secret or not totp.verify(secret, code):
            raise HTTPException(status_code=400, detail="Invalid authentication code.")
        user.mfa_enabled = False
        user.mfa_secret_encrypted = None
        audit(db, "auth.mfa_disabled", "user", user.id, actor_id=user.id)
        await notify_user(db, user.id, "account_status", {"status": "updated", "reason": "MFA was turned off."},
                          category=SECURITY)
        await db.commit()
        return {"success": "Multi-factor authentication disabled."}

    # ---- reads -------------------------------------------------------------

    async def get_user(self, id: int, db: AsyncSession):
        stmt = select(Users).where(Users.id == id).options(joinedload(Users.role_rel), joinedload(Users.status_rel))
        user_data = (await db.execute(stmt)).scalar_one_or_none()
        if not user_data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return self._public_user(
            user_data,
            user_data.role_rel.name if user_data.role_rel else None,
            user_data.status_rel.value if user_data.status_rel else None,
        )

    async def get_all_users(self, db: AsyncSession):
        stmt = select(Users).order_by(Users.created_time.desc().nullslast(), Users.id.desc())
        users_data = (await db.execute(stmt)).scalars().all()
        if not users_data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No users found")
        roles = {r.id: r.name for r in (await db.execute(select(Roles))).scalars().all()}
        statuses = {
            m.id: m.value
            for m in (await db.execute(
                select(Miscellaneous_Data).where(Miscellaneous_Data.category == "status")
            )).scalars().all()
        }
        return [self._public_user(u, roles.get(u.role_id), statuses.get(u.status)) for u in users_data]

    async def activate_deactivate_user(self, id: int, db: AsyncSession, admin_id: int | None = None):
        """Legacy admin toggle between active and inactive."""
        user_data = (await db.execute(select(Users).where(Users.id == id))).scalar_one_or_none()
        if not user_data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        active_id = await misc_id(db, "status", "active")
        inactive_id = await misc_id(db, "status", "inactive")
        if user_data.status == active_id:
            user_data.status, initial_state, final_state = inactive_id, "active", "inactive"
            await self._revoke_all_sessions(user_data.id, db)
        else:
            user_data.status, initial_state, final_state = active_id, "inactive", "active"
        audit(db, "admin.user_status_toggled", "user", user_data.id, actor_id=admin_id, actor_role="admin",
              before={"status": initial_state}, after={"status": final_state})
        await db.commit()
        return {"message": f"User {user_data.user_name} status has been changed from {initial_state} to {final_state}"}

    @staticmethod
    def _public_user(user_data: Users, role_name, user_status) -> dict:
        """User fields safe to return to clients (never the password hash or secrets)."""
        return {
            "id": user_data.id,
            "user_name": user_data.user_name,
            "first_name": user_data.first_name,
            "last_name": user_data.last_name,
            "email": user_data.email,
            "phone": user_data.phone,
            "role_id": user_data.role_id,
            "role_name": role_name,
            "status": user_data.status,
            "user_status": user_status,
            "verification_status": user_data.verification_status,
            "state": user_data.state,
            "district": user_data.district,
            "preferred_language": user_data.preferred_language,
            "created_time": user_data.created_time,
            "updated_time": user_data.updated_time,
        }

    async def _validate_location(self, state_id, district_id, db: AsyncSession):
        district_data = (await db.execute(select(Districts).where(Districts.id == district_id))).scalar_one_or_none()
        if not district_data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="District not found")
        if state_id is not None and district_data.state_id != state_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="District does not belong to the selected state",
            )

    async def get_profile(self, user_id: int, db: AsyncSession):
        stmt = (
            select(Users)
            .where(Users.id == user_id)
            .options(joinedload(Users.role_rel), joinedload(Users.state_rel), joinedload(Users.district_rel))
        )
        user_data = (await db.execute(stmt)).scalar_one_or_none()
        if not user_data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return {
            "id": user_data.id,
            "user_name": user_data.user_name,
            "first_name": user_data.first_name,
            "last_name": user_data.last_name,
            "email": user_data.email,
            "email_verified": user_data.email_verified,
            "phone": user_data.phone,
            "phone_verified": user_data.phone_verified,
            "role": user_data.role_rel.name.lower() if user_data.role_rel else None,
            "verification_status": user_data.verification_status,
            "preferred_language": user_data.preferred_language,
            "mfa_enabled": user_data.mfa_enabled,
            "state_id": user_data.state,
            "state": user_data.state_rel.state_name if user_data.state_rel else None,
            "district_id": user_data.district,
            "district": user_data.district_rel.district_name if user_data.district_rel else None,
            "deletion_requested_at": user_data.deletion_requested_at,
            "created_time": user_data.created_time,
        }

    async def update_profile(self, user_id: int, payload, db: AsyncSession):
        user_data = (await db.execute(select(Users).where(Users.id == user_id))).scalar_one_or_none()
        if not user_data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        if payload.district is not None:
            state_id = payload.state if payload.state is not None else user_data.state
            await self._validate_location(state_id, payload.district, db)
            user_data.district = payload.district
            if payload.state is not None:
                user_data.state = payload.state
        elif payload.state is not None and payload.state != user_data.state:
            user_data.state = payload.state
            user_data.district = None

        if payload.first_name:
            user_data.first_name = payload.first_name
        if payload.last_name:
            user_data.last_name = payload.last_name
        if payload.preferred_language:
            user_data.preferred_language = normalize_language(payload.preferred_language)
        user_data.updated_time = datetime.utcnow()
        user_data.updated_by = user_id
        await db.commit()
        return {"success": "Profile has been updated"}

    @staticmethod
    async def _revoke_all_sessions(user_id: int, db: AsyncSession):
        await db.execute(update(UserSessions).where(
            UserSessions.user_id == user_id, UserSessions.revoked_at.is_(None)
        ).values(revoked_at=datetime.utcnow()))
