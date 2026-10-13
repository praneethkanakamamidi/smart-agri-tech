from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import date

ExpenseCategory = Literal[
    "seed", "fertilizer", "pesticide", "labour", "irrigation", "equipment", "transport", "other"
]


class ExpenseSchema(BaseModel):
    crop: Optional[int] = None  # Leave empty for farm-wide costs
    category: ExpenseCategory
    amount: float = Field(..., gt=0)
    expense_date: date
    note: Optional[str] = Field(None, max_length=255)
