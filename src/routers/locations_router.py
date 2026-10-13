from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.location_service import LocationService
from src.db_connections.database import get_db_async
from src.services.login_service import LoginService
from src.data_models.users_model import Users

router = APIRouter(prefix="/api", tags=["Location"])

get_current_active_user = LoginService.get_current_active_user


def location_service() -> LocationService:
    return LocationService()


# Public: reference data the registration form needs before the user has an account.
@router.get("/states")
async def list_states(
    db: AsyncSession = Depends(get_db_async),
    service: LocationService = Depends(location_service),
):
    return await service.get_states(db)


@router.get("/states/{state_id}/districts")
async def list_districts(
    state_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: LocationService = Depends(location_service),
):
    return await service.get_districts(state_id, db)


@router.post("/states/", deprecated=True)
async def post_states(
    db: AsyncSession = Depends(get_db_async),
    service: LocationService = Depends(location_service),
    user: Users = Depends(get_current_active_user),
):
    """Deprecated: use GET /api/states."""
    return await service.get_states(db)


@router.put("/districts/{id}", deprecated=True)
async def put_districts(
    id: int,
    db: AsyncSession = Depends(get_db_async),
    service: LocationService = Depends(location_service),
    user: Users = Depends(get_current_active_user),
):
    """Deprecated: use GET /api/states/{state_id}/districts."""
    return await service.get_districts(id, db)
