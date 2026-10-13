from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.data_models.users_model import Users
from src.db_connections.database import get_db_async
from src.schemas.profiles_schema import FarmerProfileSchema, VendorProfileSchema, VerificationRequestSchema
from src.security_utils.role_guard import require_roles, current_user_with_role, FARMER, VENDOR
from src.services.profiles_service import ProfilesService

router = APIRouter(prefix="/api", tags=["Profiles & Verification"])


def profiles_service() -> ProfilesService:
    return ProfilesService()


@router.get("/profile")
async def get_my_profile(
    db: AsyncSession = Depends(get_db_async),
    service: ProfilesService = Depends(profiles_service),
    user: Users = Depends(current_user_with_role),
):
    return await service.get_my_profile(user, db)


@router.put("/profile/farmer")
async def upsert_farmer_profile(
    payload: FarmerProfileSchema,
    db: AsyncSession = Depends(get_db_async),
    service: ProfilesService = Depends(profiles_service),
    user: Users = Depends(require_roles(FARMER)),
):
    return await service.upsert_farmer_profile(user, payload, db)


@router.put("/profile/vendor")
async def upsert_vendor_profile(
    payload: VendorProfileSchema,
    db: AsyncSession = Depends(get_db_async),
    service: ProfilesService = Depends(profiles_service),
    user: Users = Depends(require_roles(VENDOR)),
):
    return await service.upsert_vendor_profile(user, payload, db)


@router.post("/verification")
async def submit_verification(
    payload: VerificationRequestSchema,
    db: AsyncSession = Depends(get_db_async),
    service: ProfilesService = Depends(profiles_service),
    user: Users = Depends(require_roles(FARMER, VENDOR)),
):
    return await service.submit_verification(user, payload, db)


@router.get("/verification")
async def my_verifications(
    db: AsyncSession = Depends(get_db_async),
    service: ProfilesService = Depends(profiles_service),
    user: Users = Depends(current_user_with_role),
):
    return await service.my_verifications(user, db)


@router.get("/users/{user_id}/public-profile")
async def public_profile(
    user_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: ProfilesService = Depends(profiles_service),
    user: Users = Depends(current_user_with_role),
):
    """Public farmer/vendor profile with verification badges and trust indicators."""
    return await service.public_profile(user_id, db)
