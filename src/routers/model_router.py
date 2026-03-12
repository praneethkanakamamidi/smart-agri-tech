from fastapi import APIRouter, Depends
from src.schemas.model_schema import Model_Schema
from src.data_models.users_model import Users
from src.services.model_service import ModelService
from src.services.login_service import LoginService


def get_users_service() -> ModelService:
    return ModelService()


router = APIRouter(prefix="/api", tags=["Users"])

get_current_active_user = LoginService.get_current_active_user


@router.post("/predict/")
async def predict_crop(
    payload: Model_Schema,
    model_service: ModelService = Depends(get_users_service),
    user: Users = Depends(get_current_active_user),
):
    return model_service.predict_crop(payload)
