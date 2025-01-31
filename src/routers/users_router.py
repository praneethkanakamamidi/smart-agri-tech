from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from src.services.users_service import UsersService
from src.schemas.users_schema import Add_User
from src.db_connections.postgresql_conn import get_db  # Import database session

def get_users_service() -> UsersService:
    return UsersService()

router = APIRouter(prefix="/api", tags=["Users"])

@router.post("/users")
def create_user(
    payload: Add_User,
    db: Session = Depends(get_db),
    users_service: UsersService = Depends(get_users_service),
):
    response = users_service.add_user(payload, db)
    return response

@router.get("/users/{id}")
def get_user(
    id: int,
    db: Session = Depends(get_db),
    users_service: UsersService = Depends(get_users_service),
):
    response = users_service.get_user(id, db) 
    return response
