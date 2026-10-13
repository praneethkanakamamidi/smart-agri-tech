from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import audit
from src.core.i18n import normalize_language
from src.core.lookups import misc_id
from src.core.money import D
from src.data_models.catalog_model import ProduceCategories, Units, QualityStandards
from src.data_models.crops_model import Crops
from src.helpers.serializers import model_to_dict

MODELS = {"categories": ProduceCategories, "units": Units, "quality-standards": QualityStandards}


def _localized(row, lang: str, field: str = "name") -> dict:
    data = model_to_dict(row)
    if lang == "te" and data.get(f"{field}_te"):
        data["display_name"] = data[f"{field}_te"]
    else:
        data["display_name"] = data.get(field)
    return data


class CatalogService:
    async def list_items(self, kind: str, db: AsyncSession, lang: str = "en", include_inactive: bool = False) -> list[dict]:
        model = MODELS[kind]
        stmt = select(model)
        if not include_inactive:
            stmt = stmt.where(model.is_active.is_(True))
        order = model.sort_order if kind == "quality-standards" else model.id
        rows = (await db.execute(stmt.order_by(order))).scalars().all()
        return [_localized(r, normalize_language(lang)) for r in rows]

    async def produce(self, db: AsyncSession, lang: str = "en", category_id: int | None = None) -> list[dict]:
        active_id = await misc_id(db, "status", "active")
        stmt = select(Crops).where(Crops.status == active_id)
        if category_id:
            stmt = stmt.where(Crops.category_id == category_id)
        rows = (await db.execute(stmt.order_by(Crops.crop_name))).scalars().all()
        lang = normalize_language(lang)
        return [
            {"id": c.id, "name": c.crop_name, "name_te": c.name_te, "category_id": c.category_id,
             "default_unit": c.default_unit,
             "display_name": c.name_te if lang == "te" and c.name_te else c.crop_name}
            for c in rows
        ]

    async def create(self, kind: str, payload: dict, admin_id: int, db: AsyncSession) -> dict:
        model = MODELS[kind]
        if kind == "units" and payload.get("kg_factor") is not None:
            payload["kg_factor"] = D(payload["kg_factor"])
        if kind == "categories":
            payload.setdefault("created_at", datetime.utcnow())
        row = model(**payload)
        db.add(row)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(status_code=409, detail="An entry with this name/code already exists.")
        audit(db, f"catalog.{kind}.created", kind, row.id, actor_id=admin_id, actor_role="admin", after=payload)
        await db.commit()
        return model_to_dict(row)

    async def update(self, kind: str, item_id: int, payload: dict, admin_id: int, db: AsyncSession) -> dict:
        model = MODELS[kind]
        row = (await db.execute(select(model).where(model.id == item_id))).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Not found.")
        before = model_to_dict(row)
        for key, value in payload.items():
            setattr(row, key, D(value) if key == "kg_factor" and value is not None else value)
        audit(db, f"catalog.{kind}.updated", kind, row.id, actor_id=admin_id, actor_role="admin", before=before, after=payload)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(status_code=409, detail="An entry with this name/code already exists.")
        return model_to_dict(row)

    async def update_crop_catalog(self, crop_id: int, payload: dict, admin_id: int, db: AsyncSession) -> dict:
        crop = (await db.execute(select(Crops).where(Crops.id == crop_id))).scalar_one_or_none()
        if not crop:
            raise HTTPException(status_code=404, detail="Crop not found.")
        before = {k: getattr(crop, k) for k in payload}
        for key, value in payload.items():
            setattr(crop, key, value)
        crop.updated_by, crop.updated_at = admin_id, datetime.utcnow()
        audit(db, "catalog.crop.updated", "crop", crop.id, actor_id=admin_id, actor_role="admin", before=before, after=payload)
        await db.commit()
        return {"id": crop.id, **payload}
