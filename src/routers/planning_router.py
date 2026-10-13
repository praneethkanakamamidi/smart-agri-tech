from datetime import date
from typing import Optional, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.data_models.users_model import Users
from src.db_connections.database import get_db_async
from src.security_utils.role_guard import require_roles, FARMER, VENDOR
from src.services.planning_service import PlanningService

router = APIRouter(prefix="/api", tags=["Harvest Planning & Recurring Supply"])
farmer_only = require_roles(FARMER)

DeliveryOption = Literal["pickup", "farmer_delivery", "vendor_transport", "third_party"]
PaymentTerms = Literal["full_advance", "partial_advance", "pay_before_dispatch", "pay_on_delivery", "cash_on_delivery"]


class HarvestPlanSchema(BaseModel):
    crop: int
    variety: Optional[str] = Field(None, max_length=60)
    expected_quantity: float = Field(..., gt=0)
    unit: str = Field("kg", max_length=20)
    expected_harvest_date: date
    area_acres: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = Field(None, max_length=500)


class HarvestPlanUpdateSchema(BaseModel):
    variety: Optional[str] = Field(None, max_length=60)
    expected_quantity: Optional[float] = Field(None, gt=0)
    expected_harvest_date: Optional[date] = None
    area_acres: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = Field(None, max_length=500)
    status: Optional[Literal["planned", "harvested", "cancelled"]] = None


class PublishPlanSchema(BaseModel):
    asking_price: float = Field(..., gt=0)
    min_order_qty: Optional[float] = Field(None, gt=0)
    min_acceptable_price: Optional[float] = Field(None, gt=0)
    available_until: Optional[date] = None
    description: Optional[str] = Field(None, max_length=500)
    delivery_options: list[DeliveryOption] = Field(default_factory=lambda: ["pickup"])


class RecurringProposalSchema(BaseModel):
    listing_id: int
    quantity: float = Field(..., gt=0)
    unit_price: float = Field(..., gt=0)
    frequency: Literal["weekly", "biweekly", "monthly"]
    start_date: date
    end_date: Optional[date] = None
    fulfillment_mode: DeliveryOption = "pickup"
    payment_terms: PaymentTerms = "pay_before_dispatch"
    notes: Optional[str] = Field(None, max_length=500)


def planning_service() -> PlanningService:
    return PlanningService()


@router.post("/harvest-plans")
async def create_plan(payload: HarvestPlanSchema, db: AsyncSession = Depends(get_db_async),
                      service: PlanningService = Depends(planning_service), user: Users = Depends(farmer_only)):
    return await service.create_plan(user, payload, db)


@router.get("/harvest-plans/calendar")
async def harvest_calendar(date_from: Optional[date] = None, date_to: Optional[date] = None,
                           db: AsyncSession = Depends(get_db_async), service: PlanningService = Depends(planning_service),
                           user: Users = Depends(farmer_only)):
    """Upcoming harvests with expected quantities."""
    return await service.calendar(user, db, date_from, date_to)


@router.put("/harvest-plans/{plan_id}")
async def update_plan(plan_id: int, payload: HarvestPlanUpdateSchema, db: AsyncSession = Depends(get_db_async),
                      service: PlanningService = Depends(planning_service), user: Users = Depends(farmer_only)):
    return await service.update_plan(user, plan_id, payload, db)


@router.post("/harvest-plans/{plan_id}/publish")
async def publish_plan(plan_id: int, payload: PublishPlanSchema, db: AsyncSession = Depends(get_db_async),
                       service: PlanningService = Depends(planning_service), user: Users = Depends(farmer_only)):
    """Open a planned harvest for pre-harvest booking (clearly marked as not yet available)."""
    return await service.publish_plan(user, plan_id, payload, db)


@router.post("/recurring-orders")
async def propose_recurring(payload: RecurringProposalSchema, db: AsyncSession = Depends(get_db_async),
                            service: PlanningService = Depends(planning_service), user: Users = Depends(require_roles(VENDOR))):
    """Propose a recurring supply at a fixed price. Orders are created only after the farmer approves."""
    return await service.propose_recurring(user, payload, db)


@router.get("/recurring-orders")
async def list_recurring(db: AsyncSession = Depends(get_db_async), service: PlanningService = Depends(planning_service),
                         user: Users = Depends(require_roles(FARMER, VENDOR))):
    return await service.list_recurring(user, db)


@router.post("/recurring-orders/{recurring_id}/{action}")
async def change_recurring(recurring_id: int, action: Literal["approve", "reject", "pause", "resume", "cancel"],
                           db: AsyncSession = Depends(get_db_async), service: PlanningService = Depends(planning_service),
                           user: Users = Depends(require_roles(FARMER, VENDOR))):
    return await service.change_recurring(user, recurring_id, action, db)
