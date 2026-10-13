"""Cached ids for rows of the miscellaneous_data lookup table (statuses never change id)."""
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data_models.miscellaneous_model import Miscellaneous_Data

_ids: dict[tuple[str, str], int] = {}
_values: dict[int, str] = {}


async def misc_id(db: AsyncSession, category: str, value: str) -> int:
    key = (category, value)
    if key not in _ids:
        row = (await db.execute(select(Miscellaneous_Data.id).where(
            Miscellaneous_Data.category == category, Miscellaneous_Data.value == value,
        ))).scalar_one_or_none()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Lookup value {category}/{value} is missing. Run the database migrations.",
            )
        _ids[key] = row
        _values[row] = value
    return _ids[key]


async def misc_value(db: AsyncSession, misc_id_: int | None) -> str | None:
    if misc_id_ is None:
        return None
    if misc_id_ not in _values:
        row = (await db.execute(select(Miscellaneous_Data.value).where(Miscellaneous_Data.id == misc_id_))).scalar_one_or_none()
        if row is None:
            return None
        _values[misc_id_] = row
    return _values[misc_id_]


def clear_cache():
    _ids.clear()
    _values.clear()
