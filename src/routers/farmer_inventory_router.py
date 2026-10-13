"""Legacy /inventory endpoints, kept for existing clients. New clients should use /api/listings."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.data_models.users_model import Users
from src.db_connections.database import get_db_async
from src.schemas.farmer_inventory_schema import AddFarmerInventorySchema, UpdateFarmerInventorySchema
from src.schemas.listings_schema import ListingCreateSchema, ListingUpdateSchema
from src.security_utils.role_guard import require_roles, current_user_with_role, FARMER
from src.services.listings_service import ListingsService

router = APIRouter(prefix="/api", tags=["Inventory (legacy)"])


def listings_service() -> ListingsService:
    return ListingsService()


@router.post("/inventory/", deprecated=True)
async def post_stock_data(
    payload: AddFarmerInventorySchema,
    db: AsyncSession = Depends(get_db_async),
    service: ListingsService = Depends(listings_service),
    user: Users = Depends(require_roles(FARMER)),
):
    if payload.crop is None or payload.weight_kg is None or not payload.proposed_cost:
        raise HTTPException(status_code=422, detail="crop, weight_kg and proposed_cost are required.")
    create = ListingCreateSchema(
        crop=payload.crop, fertilizer=payload.fertilizer, soil=payload.soil, quantity=payload.weight_kg,
        unit="kg", asking_price=payload.proposed_cost, description=payload.description,
        quality_grade=payload.quality_grade, harvest_date=payload.harvest_date,
        available_until=payload.available_until, publish=payload.weight_kg > 0,
    )
    return await service.create(user, create, db)


@router.put("/inventory/", deprecated=True)
async def put_stock_data(
    payload: UpdateFarmerInventorySchema,
    db: AsyncSession = Depends(get_db_async),
    service: ListingsService = Depends(listings_service),
    user: Users = Depends(require_roles(FARMER)),
):
    if payload.id is None:
        raise HTTPException(status_code=422, detail="id is required.")
    update = ListingUpdateSchema(**{
        k: v for k, v in {
            "quantity": payload.weight_kg, "asking_price": payload.proposed_cost, "description": payload.description,
            "quality_grade": payload.quality_grade, "harvest_date": payload.harvest_date,
            "available_until": payload.available_until,
        }.items() if v is not None
    })
    return await service.update(user, payload.id, update, db)


@router.get("/inventory/stock/{id}", deprecated=True)
async def get_stock_data(
    id: int,
    db: AsyncSession = Depends(get_db_async),
    service: ListingsService = Depends(listings_service),
    user: Users = Depends(current_user_with_role),
):
    return await service.detail(id, user, db)


@router.get("/inventory/stocks/{user_id}", deprecated=True)
async def get_stocks_data(
    user_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: ListingsService = Depends(listings_service),
    user: Users = Depends(current_user_with_role),
):
    return await service.farmer_listings(user_id, user, db)


@router.delete("/delete-stock/{id}", deprecated=True)
async def stock_data_status(
    id: int,
    db: AsyncSession = Depends(get_db_async),
    service: ListingsService = Depends(listings_service),
    user: Users = Depends(require_roles(FARMER)),
):
    return await service.delete(user, id, db)
