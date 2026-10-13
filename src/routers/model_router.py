from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from src.schemas.model_schema import Model_Schema
from src.data_models.users_model import Users
from src.services.model_service import ModelService
from src.services.login_service import LoginService


def get_model_service() -> ModelService:
    return ModelService()


router = APIRouter(prefix="/api", tags=["Crop Recommendation"])

get_current_active_user = LoginService.get_current_active_user


@router.post("/predict/")
async def predict_crop(
    payload: Model_Schema,
    model_service: ModelService = Depends(get_model_service),
    user: Users = Depends(get_current_active_user),
):
    # scikit-learn inference is CPU-bound; keep it off the event loop.
    return await run_in_threadpool(model_service.predict_crop, payload)
