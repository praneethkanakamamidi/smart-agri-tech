from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.services.crops_service import CropService
from src.db_connections.postgresql_conn import get_db
from src.services.login_service import LoginService
from src.data_models.users_model import Users
from src.schemas.crops_schema import CropsSchema, UpdateCropSchema, CropStatus

router = APIRouter(prefix="/api", tags=["Crops"])

get_current_active_user = LoginService.get_current_active_user

def crops_service() -> CropService:
    return CropService()

@router.post("/crops/")
def post_crops_data(
    payload: CropsSchema,
    db: Session = Depends(get_db),
    service: CropService = Depends(crops_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.post_crop(payload, db)
    return response

@router.put("/crops/")
def put_crops_data(
    payload: UpdateCropSchema,
    db: Session = Depends(get_db), 
    service: CropService = Depends(crops_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.put_crop(payload, db)
    return response

@router.get("/crops/{id}")
def get_crop_data(
    id: int, 
    db: Session = Depends(get_db), 
    service: CropService = Depends(crops_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.get_crop(id, db)
    return response

@router.get("/crops/")
def get_crops_data(
    db: Session = Depends(get_db), 
    service: CropService = Depends(crops_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.get_crops(db)
    return response

@router.put("/crops-status/")
def crop_data_status(
    payload: CropStatus,
    db: Session = Depends(get_db), 
    service: CropService = Depends(crops_service),
    user: Users = Depends(get_current_active_user)
):
    response = service.crop_status(payload, db)
    return response