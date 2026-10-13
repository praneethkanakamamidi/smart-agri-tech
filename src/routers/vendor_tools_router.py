from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.favourites_service import FavouritesService
from src.services.crop_alerts_service import CropAlertsService
from src.db_connections.database import get_db_async
from src.data_models.users_model import Users
from src.schemas.vendor_tools_schema import CreateCropAlertSchema
from src.security_utils.role_guard import require_roles, VENDOR

router = APIRouter(prefix="/api", tags=["Favourites & Alerts"])

vendor_only = require_roles(VENDOR)


def favourites_service() -> FavouritesService:
    return FavouritesService()


def crop_alerts_service() -> CropAlertsService:
    return CropAlertsService()


# ---- Favourite farmers ----

@router.get("/favourites")
async def list_favourites(
    db: AsyncSession = Depends(get_db_async),
    service: FavouritesService = Depends(favourites_service),
    user: Users = Depends(vendor_only),
):
    return await service.list_favourites(user.id, db)


@router.get("/favourites/feed")
async def favourites_feed(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_async),
    service: FavouritesService = Depends(favourites_service),
    user: Users = Depends(vendor_only),
):
    return await service.get_feed(user.id, db, page, page_size)


@router.post("/favourites/{farmer_id}")
async def add_favourite(
    farmer_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: FavouritesService = Depends(favourites_service),
    user: Users = Depends(vendor_only),
):
    return await service.add_favourite(farmer_id, user.id, db)


@router.delete("/favourites/{farmer_id}")
async def remove_favourite(
    farmer_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: FavouritesService = Depends(favourites_service),
    user: Users = Depends(vendor_only),
):
    return await service.remove_favourite(farmer_id, user.id, db)


# ---- Crop alerts (saved searches) ----

@router.post("/crop-alerts")
async def create_crop_alert(
    payload: CreateCropAlertSchema,
    db: AsyncSession = Depends(get_db_async),
    service: CropAlertsService = Depends(crop_alerts_service),
    user: Users = Depends(vendor_only),
):
    return await service.create_alert(payload, user.id, db)


@router.get("/crop-alerts")
async def list_crop_alerts(
    db: AsyncSession = Depends(get_db_async),
    service: CropAlertsService = Depends(crop_alerts_service),
    user: Users = Depends(vendor_only),
):
    return await service.list_alerts(user.id, db)


@router.put("/crop-alerts/{alert_id}/toggle")
async def toggle_crop_alert(
    alert_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: CropAlertsService = Depends(crop_alerts_service),
    user: Users = Depends(vendor_only),
):
    return await service.toggle_alert(alert_id, user.id, db)


@router.delete("/crop-alerts/{alert_id}")
async def delete_crop_alert(
    alert_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: CropAlertsService = Depends(crop_alerts_service),
    user: Users = Depends(vendor_only),
):
    return await service.delete_alert(alert_id, user.id, db)
