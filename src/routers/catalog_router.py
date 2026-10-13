from typing import Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.data_models.users_model import Users
from src.db_connections.database import get_db_async
from src.security_utils.role_guard import require_roles, current_user_with_role, ADMIN
from src.services.catalog_service import CatalogService

router = APIRouter(prefix="/api", tags=["Catalog"])
admin_only = require_roles(ADMIN)


class CategorySchema(BaseModel):
    name: Optional[str] = Field(None, max_length=60)
    name_te: Optional[str] = Field(None, max_length=60)
    parent_id: Optional[int] = None
    is_active: Optional[bool] = None


class UnitSchema(BaseModel):
    code: Optional[str] = Field(None, max_length=20, pattern=r"^[a-z_]+$")
    name: Optional[str] = Field(None, max_length=40)
    name_te: Optional[str] = Field(None, max_length=40)
    kg_factor: Optional[float] = Field(None, gt=0)
    is_active: Optional[bool] = None


class QualityStandardSchema(BaseModel):
    code: Optional[str] = Field(None, max_length=10)
    name: Optional[str] = Field(None, max_length=40)
    name_te: Optional[str] = Field(None, max_length=40)
    description: Optional[str] = Field(None, max_length=255)
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class CropCatalogSchema(BaseModel):
    category_id: Optional[int] = None
    name_te: Optional[str] = Field(None, max_length=100)
    default_unit: Optional[str] = Field(None, max_length=20)


def catalog_service() -> CatalogService:
    return CatalogService()


def _lang(user: Users, accept_language: Optional[str]) -> str:
    return accept_language or user.preferred_language


@router.get("/catalog/categories")
async def categories(accept_language: Optional[str] = Header(None), db: AsyncSession = Depends(get_db_async),
                     service: CatalogService = Depends(catalog_service), user: Users = Depends(current_user_with_role)):
    return await service.list_items("categories", db, _lang(user, accept_language))


@router.get("/catalog/units")
async def units(accept_language: Optional[str] = Header(None), db: AsyncSession = Depends(get_db_async),
                service: CatalogService = Depends(catalog_service), user: Users = Depends(current_user_with_role)):
    return await service.list_items("units", db, _lang(user, accept_language))


@router.get("/catalog/quality-standards")
async def quality_standards(accept_language: Optional[str] = Header(None), db: AsyncSession = Depends(get_db_async),
                            service: CatalogService = Depends(catalog_service), user: Users = Depends(current_user_with_role)):
    return await service.list_items("quality-standards", db, _lang(user, accept_language))


@router.get("/catalog/produce")
async def produce(category_id: Optional[int] = None, accept_language: Optional[str] = Header(None),
                  db: AsyncSession = Depends(get_db_async), service: CatalogService = Depends(catalog_service),
                  user: Users = Depends(current_user_with_role)):
    """Active produce items with localised names."""
    return await service.produce(db, _lang(user, accept_language), category_id)


@router.post("/admin/catalog/categories")
async def create_category(payload: CategorySchema, db: AsyncSession = Depends(get_db_async),
                          service: CatalogService = Depends(catalog_service), user: Users = Depends(admin_only)):
    return await service.create("categories", payload.model_dump(exclude_none=True), user.id, db)


@router.put("/admin/catalog/categories/{item_id}")
async def update_category(item_id: int, payload: CategorySchema, db: AsyncSession = Depends(get_db_async),
                          service: CatalogService = Depends(catalog_service), user: Users = Depends(admin_only)):
    return await service.update("categories", item_id, payload.model_dump(exclude_unset=True), user.id, db)


@router.post("/admin/catalog/units")
async def create_unit(payload: UnitSchema, db: AsyncSession = Depends(get_db_async),
                      service: CatalogService = Depends(catalog_service), user: Users = Depends(admin_only)):
    return await service.create("units", payload.model_dump(exclude_none=True), user.id, db)


@router.put("/admin/catalog/units/{item_id}")
async def update_unit(item_id: int, payload: UnitSchema, db: AsyncSession = Depends(get_db_async),
                      service: CatalogService = Depends(catalog_service), user: Users = Depends(admin_only)):
    return await service.update("units", item_id, payload.model_dump(exclude_unset=True), user.id, db)


@router.post("/admin/catalog/quality-standards")
async def create_quality_standard(payload: QualityStandardSchema, db: AsyncSession = Depends(get_db_async),
                                  service: CatalogService = Depends(catalog_service), user: Users = Depends(admin_only)):
    return await service.create("quality-standards", payload.model_dump(exclude_none=True), user.id, db)


@router.put("/admin/catalog/quality-standards/{item_id}")
async def update_quality_standard(item_id: int, payload: QualityStandardSchema, db: AsyncSession = Depends(get_db_async),
                                  service: CatalogService = Depends(catalog_service), user: Users = Depends(admin_only)):
    return await service.update("quality-standards", item_id, payload.model_dump(exclude_unset=True), user.id, db)


@router.put("/admin/catalog/produce/{crop_id}")
async def update_produce(crop_id: int, payload: CropCatalogSchema, db: AsyncSession = Depends(get_db_async),
                         service: CatalogService = Depends(catalog_service), user: Users = Depends(admin_only)):
    """Set a produce item's category, Telugu name and default unit."""
    return await service.update_crop_catalog(crop_id, payload.model_dump(exclude_unset=True), user.id, db)
