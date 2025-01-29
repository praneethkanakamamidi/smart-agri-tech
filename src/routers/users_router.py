from fastapi import APIRouter, Depends, HTTPException, status
from src.services.users_service import Users_Service
from src.schemas.users_schema import Add_User

def get_users_service() -> Users_Service:
    return Users_Service()

router = APIRouter(prefix="/api", tags=["Users"])

@router.post("/users")
def create_user(
    payload: Add_User,
    users_service: Users_Service = Depends(get_users_service)
):
    response = users_service.add_user(payload)    
    return response
