from fastapi import HTTPException, status
from sqlalchemy import select, func, extract
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from src.data_models.farm_expenses_model import FarmExpenses
from src.data_models.orders_model import Orders
from src.data_models.transactions_model import Transactions
from src.data_models.farmer_inventory_model import FarmerInventory
from src.data_models.crops_model import Crops
from src.data_models.miscellaneous_model import Miscellaneous_Data
from src.helpers.serializers import model_to_dict


class ExpensesService:
    """Farmer cost tracking and profit per crop (paid revenue - expenses)."""

    async def _get_owned(self, expense_id: int, farmer_id: int, db: AsyncSession) -> FarmExpenses:
        expense = (await db.execute(select(FarmExpenses).where(FarmExpenses.id == expense_id))).scalar_one_or_none()
        if not expense or expense.farmer != farmer_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found.")
        return expense

    async def add_expense(self, payload, farmer_id: int, db: AsyncSession):
        try:
            expense = FarmExpenses(
                farmer=farmer_id,
                crop=payload.crop,
                category=payload.category,
                amount=payload.amount,
                expense_date=payload.expense_date,
                note=payload.note,
                created_at=datetime.utcnow(),
            )
            db.add(expense)
            await db.commit()
            return {"success": "Expense added.", "expense_id": expense.id}
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def update_expense(self, expense_id: int, payload, farmer_id: int, db: AsyncSession):
        try:
            expense = await self._get_owned(expense_id, farmer_id, db)
            expense.crop = payload.crop
            expense.category = payload.category
            expense.amount = payload.amount
            expense.expense_date = payload.expense_date
            expense.note = payload.note
            expense.updated_at = datetime.utcnow()
            await db.commit()
            return {"success": "Expense updated."}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def delete_expense(self, expense_id: int, farmer_id: int, db: AsyncSession):
        try:
            expense = await self._get_owned(expense_id, farmer_id, db)
            await db.delete(expense)
            await db.commit()
            return {"success": "Expense deleted."}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def list_expenses(
        self, farmer_id: int, db: AsyncSession, year=None, crop_id=None, category=None,
        page: int = 1, page_size: int = 20,
    ):
        try:
            filters = [FarmExpenses.farmer == farmer_id]
            if year:
                filters.append(extract("year", FarmExpenses.expense_date) == year)
            if crop_id:
                filters.append(FarmExpenses.crop == crop_id)
            if category:
                filters.append(FarmExpenses.category == category)

            total_records = (await db.execute(select(func.count(FarmExpenses.id)).where(*filters))).scalar() or 0
            stmt = (
                select(FarmExpenses)
                .where(*filters)
                .options(joinedload(FarmExpenses.crop_rel))
                .order_by(FarmExpenses.expense_date.desc(), FarmExpenses.id.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
            expenses = (await db.execute(stmt)).scalars().unique().all()
            return {
                "page": page,
                "page_size": page_size,
                "total_records": total_records,
                "total_pages": (total_records + page_size - 1) // page_size,
                "data": [
                    model_to_dict(e, crop_name=e.crop_rel.crop_name if e.crop_rel else None)
                    for e in expenses
                ],
            }
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )

    async def get_summary(self, farmer_id: int, db: AsyncSession, year=None):
        """Expenses by category and by crop, paid revenue by crop, and profit."""
        try:
            expense_filters = [FarmExpenses.farmer == farmer_id]
            if year:
                expense_filters.append(extract("year", FarmExpenses.expense_date) == year)

            by_category = {
                category: round(float(total), 2)
                for category, total in (await db.execute(
                    select(FarmExpenses.category, func.sum(FarmExpenses.amount))
                    .where(*expense_filters)
                    .group_by(FarmExpenses.category)
                )).all()
            }

            expense_by_crop = {
                crop_id: float(total)
                for crop_id, total in (await db.execute(
                    select(FarmExpenses.crop, func.sum(FarmExpenses.amount))
                    .where(*expense_filters)
                    .group_by(FarmExpenses.crop)
                )).all()
            }

            revenue_filters = [Orders.farmer == farmer_id, Miscellaneous_Data.value == "paid"]
            if year:
                revenue_filters.append(extract("year", Transactions.created_at) == year)
            revenue_by_crop = {
                crop_id: float(total)
                for crop_id, total in (await db.execute(
                    select(FarmerInventory.crop, func.sum(Transactions.amount_paid))
                    .select_from(Transactions)
                    .join(Orders, Transactions.order_id == Orders.id)
                    .join(FarmerInventory, Orders.farmer_inventory == FarmerInventory.id)
                    .join(Miscellaneous_Data, Transactions.status == Miscellaneous_Data.id)
                    .where(*revenue_filters)
                    .group_by(FarmerInventory.crop)
                )).all()
            }

            crop_ids = {c for c in (*expense_by_crop, *revenue_by_crop) if c is not None}
            crop_names = {}
            if crop_ids:
                crop_names = dict((await db.execute(
                    select(Crops.id, Crops.crop_name).where(Crops.id.in_(crop_ids))
                )).all())

            by_crop = []
            for crop_id in sorted(crop_ids):
                revenue = revenue_by_crop.get(crop_id, 0.0)
                expenses = expense_by_crop.get(crop_id, 0.0)
                by_crop.append({
                    "crop_id": crop_id,
                    "crop_name": crop_names.get(crop_id),
                    "revenue": round(revenue, 2),
                    "expenses": round(expenses, 2),
                    "profit": round(revenue - expenses, 2),
                })

            total_expenses = sum(expense_by_crop.values())
            total_revenue = sum(revenue_by_crop.values())
            return {
                "year": year,
                "total_revenue": round(total_revenue, 2),
                "total_expenses": round(total_expenses, 2),
                "net_profit": round(total_revenue - total_expenses, 2),
                "general_expenses": round(expense_by_crop.get(None, 0.0), 2),
                "expenses_by_category": by_category,
                "by_crop": by_crop,
            }
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )
