from typing import Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.market_service import MarketService
from src.db_connections.database import get_db_async
from src.services.login_service import LoginService
from src.data_models.users_model import Users
from src.schemas.listings_schema import MarketFilters

router = APIRouter(prefix="/api", tags=["Market"])

get_current_active_user = LoginService.get_current_active_user


def market_service() -> MarketService:
    return MarketService()


@router.get("/market/")
async def get_market_data(
    filters: Annotated[MarketFilters, Query()],
    db: AsyncSession = Depends(get_db_async),
    service: MarketService = Depends(market_service),
    user: Users = Depends(get_current_active_user),
):
    """Search live listings. Prices shown are asking prices; the final price is negotiated."""
    return await service.get_market(db, filters, user.id)
