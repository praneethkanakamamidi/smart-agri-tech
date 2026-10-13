from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data_models.roles_model import Roles
from src.data_models.users_model import Users
from src.db_connections.database import get_db_async
from src.services.login_service import LoginService, admin_mfa_required

FARMER = "farmer"
VENDOR = "vendor"
ADMIN = "admin"

_role_names: dict[int, str | None] = {}


async def get_role_name(user: Users, db: AsyncSession) -> str | None:
    if user.role_id not in _role_names:
        name = (await db.execute(select(Roles.name).where(Roles.id == user.role_id))).scalar_one_or_none()
        _role_names[user.role_id] = name.lower() if name else None
    return _role_names[user.role_id]


async def role_id_for(db: AsyncSession, role_name: str) -> int | None:
    return (await db.execute(
        select(Roles.id).where(Roles.name.ilike(role_name))
    )).scalar_one_or_none()


def require_roles(*roles: str):
    """Dependency factory: allow only users whose role name is in `roles`."""
    allowed = {r.lower() for r in roles}

    async def checker(
        user: Users = Depends(LoginService.get_current_active_user),
        db: AsyncSession = Depends(get_db_async),
    ) -> Users:
        role_name = await get_role_name(user, db)
        if role_name not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: This action is allowed only for {', '.join(sorted(allowed))}.",
            )
        if role_name == ADMIN and admin_mfa_required() and not user.mfa_enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin accounts must enable multi-factor authentication (POST /api/auth/mfa/setup).",
            )
        user.role_name = role_name
        return user

    return checker


async def current_user_with_role(
    user: Users = Depends(LoginService.get_current_active_user),
    db: AsyncSession = Depends(get_db_async),
) -> Users:
    """Any authenticated user, with `user.role_name` populated."""
    user.role_name = await get_role_name(user, db)
    return user
