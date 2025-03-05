from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.services.market_service import MarketService
from src.db_connections.postgresql_conn import get_db
from src.services.login_service import LoginService
from src.data_models.users_model import Users

router = APIRouter(prefix="/api", tags=["Market"])

get_current_active_user = LoginService.get_current_active_user

def market_service() -> MarketService:
    return MarketService()

@router.get("/market/")
def get_market_data(
    db: Session = Depends(get_db), 
    service: MarketService = Depends(market_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.get_market(db)
    return response