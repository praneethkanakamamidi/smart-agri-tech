from fastapi import APIRouter, Depends
from src.schemas.model_schema import Model_Schema
from src.db_connections.postgresql_conn import get_db  # Import database session
from src.data_models.users_model import Users
from src.services.model_service import ModelService

def get_users_service() -> ModelService:
    return ModelService()

router = APIRouter(prefix="/api", tags=["Users"])

get_current_active_user = ModelService.model_service

@router.post("/predict")
def predict_crop(
    payload: Model_Schema,
    model_service: ModelService = Depends(get_users_service),
    # user: Users = Depends(get_current_active_user)
):
    response = model_service.model_service(payload)
    return response
