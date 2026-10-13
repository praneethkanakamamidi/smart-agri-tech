from datetime import date
from typing import Optional, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.data_models.users_model import Users
from src.db_connections.database import get_db_async
from src.security_utils.role_guard import require_roles, current_user_with_role, FARMER, VENDOR, ADMIN
from src.services.analytics_service import AnalyticsService
from src.services.dashboard_service import DashboardService
from src.services.insights_service import InsightsService

router = APIRouter(prefix="/api", tags=["Insights, Dashboards & Reports"])


def insights_service() -> InsightsService:
    return InsightsService()


def dashboard_service() -> DashboardService:
    return DashboardService()


def analytics_service() -> AnalyticsService:
    return AnalyticsService()


@router.get("/insights/prices")
async def price_insights(
    crop_id: int, state_id: Optional[int] = None, district_id: Optional[int] = None,
    days: int = Query(30, ge=1, le=365), variety: Optional[str] = None, quality_grade: Optional[str] = None,
    unit: Optional[str] = None, db: AsyncSession = Depends(get_db_async),
    service: InsightsService = Depends(insights_service), user: Users = Depends(current_user_with_role),
):
    """Asking prices vs negotiated prices (separately), with median, range, sample size and reliability."""
    return await service.get_price_insights(crop_id, db, state_id, district_id, days, variety, quality_grade, unit)


@router.get("/insights/prices/trend")
async def price_trend(
    crop_id: int, state_id: Optional[int] = None, district_id: Optional[int] = None,
    weeks: int = Query(12, ge=1, le=104), quality_grade: Optional[str] = None, unit: Optional[str] = None,
    db: AsyncSession = Depends(get_db_async), service: InsightsService = Depends(insights_service),
    user: Users = Depends(current_user_with_role),
):
    return await service.get_price_trend(crop_id, db, state_id, district_id, weeks, quality_grade, unit)


@router.get("/insights/listings/{listing_id}/price-check")
async def listing_price_check(
    listing_id: int, db: AsyncSession = Depends(get_db_async),
    service: InsightsService = Depends(insights_service), user: Users = Depends(require_roles(FARMER)),
):
    """How your asking price compares with recent negotiated prices nearby."""
    return await service.listing_price_check(user, listing_id, db)


@router.get("/insights/procurement")
async def procurement_trend(
    crop_id: Optional[int] = None, months: int = Query(6, ge=1, le=24), db: AsyncSession = Depends(get_db_async),
    service: InsightsService = Depends(insights_service), user: Users = Depends(require_roles(VENDOR)),
):
    return await service.procurement_trend(user, db, crop_id, months)


@router.get("/insights/demand-forecast")
async def demand_forecast(
    crop_id: int, weeks_history: int = Query(12, ge=4, le=52), horizon: int = Query(4, ge=1, le=12),
    db: AsyncSession = Depends(get_db_async), service: InsightsService = Depends(insights_service),
    user: Users = Depends(current_user_with_role),
):
    return await service.demand_forecast(crop_id, db, weeks_history, horizon)


@router.get("/dashboard/farmer")
async def farmer_dashboard(db: AsyncSession = Depends(get_db_async), service: DashboardService = Depends(dashboard_service),
                           user: Users = Depends(require_roles(FARMER))):
    return await service.farmer_dashboard(user.id, db)


@router.get("/dashboard/vendor")
async def vendor_dashboard(db: AsyncSession = Depends(get_db_async), service: DashboardService = Depends(dashboard_service),
                           user: Users = Depends(require_roles(VENDOR))):
    return await service.vendor_dashboard(user.id, db)


@router.get("/reports/farmer")
async def farmer_report(
    period: Literal["day", "week", "month"] = "month", date_from: Optional[date] = None, date_to: Optional[date] = None,
    db: AsyncSession = Depends(get_db_async), service: AnalyticsService = Depends(analytics_service),
    user: Users = Depends(require_roles(FARMER)),
):
    return await service.farmer_report(user, db, period, date_from, date_to)


@router.get("/reports/vendor")
async def vendor_report(
    period: Literal["day", "week", "month"] = "month", date_from: Optional[date] = None, date_to: Optional[date] = None,
    db: AsyncSession = Depends(get_db_async), service: AnalyticsService = Depends(analytics_service),
    user: Users = Depends(require_roles(VENDOR)),
):
    return await service.vendor_report(user, db, period, date_from, date_to)


@router.get("/vendor/suppliers/compare")
async def compare_suppliers(
    farmer_ids: list[int] = Query(...), crop_id: Optional[int] = None, db: AsyncSession = Depends(get_db_async),
    service: AnalyticsService = Depends(analytics_service), user: Users = Depends(require_roles(VENDOR)),
):
    """Side-by-side: trust indicators, live listings and past deal prices for up to 10 farmers."""
    return await service.compare_suppliers(user, db, farmer_ids, crop_id)


@router.get("/admin/analytics")
async def admin_report(
    date_from: Optional[date] = None, date_to: Optional[date] = None, db: AsyncSession = Depends(get_db_async),
    service: AnalyticsService = Depends(analytics_service), user: Users = Depends(require_roles(ADMIN)),
):
    return await service.admin_report(db, date_from, date_to)


@router.get("/admin/metrics/success")
async def success_metrics(
    weeks: int = Query(4, ge=1, le=52), db: AsyncSession = Depends(get_db_async),
    service: AnalyticsService = Depends(analytics_service), user: Users = Depends(require_roles(ADMIN)),
):
    """Liquidity, negotiation effectiveness, reliability and user value metrics."""
    return await service.success_metrics(db, weeks)
