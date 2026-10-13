from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.expenses_service import ExpensesService
from src.db_connections.database import get_db_async
from src.data_models.users_model import Users
from src.schemas.expenses_schema import ExpenseSchema
from src.security_utils.role_guard import require_roles, FARMER

router = APIRouter(prefix="/api", tags=["Farm Expenses"])

farmer_only = require_roles(FARMER)


def expenses_service() -> ExpensesService:
    return ExpensesService()


@router.post("/expenses")
async def add_expense(
    payload: ExpenseSchema,
    db: AsyncSession = Depends(get_db_async),
    service: ExpensesService = Depends(expenses_service),
    user: Users = Depends(farmer_only),
):
    return await service.add_expense(payload, user.id, db)


@router.get("/expenses")
async def list_expenses(
    year: Optional[int] = None,
    crop_id: Optional[int] = None,
    category: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_async),
    service: ExpensesService = Depends(expenses_service),
    user: Users = Depends(farmer_only),
):
    return await service.list_expenses(user.id, db, year, crop_id, category, page, page_size)


@router.get("/expenses/summary")
async def expenses_summary(
    year: Optional[int] = None,
    db: AsyncSession = Depends(get_db_async),
    service: ExpensesService = Depends(expenses_service),
    user: Users = Depends(farmer_only),
):
    return await service.get_summary(user.id, db, year)


@router.put("/expenses/{expense_id}")
async def update_expense(
    expense_id: int,
    payload: ExpenseSchema,
    db: AsyncSession = Depends(get_db_async),
    service: ExpensesService = Depends(expenses_service),
    user: Users = Depends(farmer_only),
):
    return await service.update_expense(expense_id, payload, user.id, db)


@router.delete("/expenses/{expense_id}")
async def delete_expense(
    expense_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: ExpensesService = Depends(expenses_service),
    user: Users = Depends(farmer_only),
):
    return await service.delete_expense(expense_id, user.id, db)
