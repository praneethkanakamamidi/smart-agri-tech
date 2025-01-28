from fastapi import APIRouter, Depends
from src.services.miscellaneous_service import Miscellaneous_Data_Service

miscellaneous_data_service = Miscellaneous_Data_Service()

router = APIRouter(prefix="/api")

@router.get("/miscellaneous/{id}")
def login(id:int):
    response = miscellaneous_data_service.get_miscellaneous_data(id)
    return response
