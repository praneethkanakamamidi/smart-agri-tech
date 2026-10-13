from datetime import datetime
from typing import Optional, Literal, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.data_models.users_model import Users
from src.db_connections.database import get_db_async
from src.schemas.payment_schema import RefundSchema, MarkRefundedSchema, SettlementPayoutSchema
from src.schemas.reviews_schema import ModerateReviewSchema
from src.security_utils.role_guard import require_roles, ADMIN
from src.services.admin_service import AdminService
from src.services.orders_service import OrdersService
from src.services.payment_service import PaymentsService
from src.services.reviews_service import ReviewsService

router = APIRouter(prefix="/api/admin", tags=["Admin"])
admin_only = require_roles(ADMIN)


class UserStatusSchema(BaseModel):
    status: Literal["active", "inactive", "suspended"]
    reason: str = Field(..., min_length=3, max_length=255)


class DecisionSchema(BaseModel):
    decision: str
    notes: Optional[str] = Field(None, max_length=500)


class VerificationDecisionSchema(BaseModel):
    decision: Literal["VERIFIED", "REJECTED"]
    notes: Optional[str] = Field(None, max_length=500)


class AppealDecisionSchema(BaseModel):
    accept: bool
    notes: Optional[str] = Field(None, max_length=500)


class ListingModerationSchema(BaseModel):
    action: Literal["remove", "restore"]
    reason: str = Field(..., min_length=3, max_length=255)


class CertificationDecisionSchema(BaseModel):
    decision: Literal["verified", "rejected"]
    notes: Optional[str] = Field(None, max_length=255)


class ReportDecisionSchema(BaseModel):
    decision: Literal["actioned", "dismissed"]
    notes: Optional[str] = Field(None, max_length=500)


class AdjustmentSchema(BaseModel):
    amount: float = Field(..., description="Positive increases the amount payable, negative decreases it.")
    reason: str = Field(..., min_length=5, max_length=500)


class SettingSchema(BaseModel):
    value: Any
    reason: Optional[str] = Field(None, max_length=255)


class AnnouncementSchema(BaseModel):
    title: str = Field(..., max_length=150)
    body: str = Field(..., max_length=5000)
    title_te: Optional[str] = Field(None, max_length=150)
    body_te: Optional[str] = Field(None, max_length=5000)
    audience: Literal["all", "farmer", "vendor"] = "all"
    is_promotional: bool = False
    is_active: bool = True
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    notify: bool = False


class AnnouncementUpdateSchema(BaseModel):
    title: Optional[str] = Field(None, max_length=150)
    body: Optional[str] = Field(None, max_length=5000)
    title_te: Optional[str] = Field(None, max_length=150)
    body_te: Optional[str] = Field(None, max_length=5000)
    audience: Optional[Literal["all", "farmer", "vendor"]] = None
    is_active: Optional[bool] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None


def admin_service() -> AdminService:
    return AdminService()


# ---- users / verification / appeals ----

@router.get("/users")
async def search_users(q: Optional[str] = None, role: Optional[str] = None, status: Optional[str] = None,
                       verification_status: Optional[str] = None, page: int = Query(1, ge=1),
                       page_size: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_db_async),
                       service: AdminService = Depends(admin_service), user: Users = Depends(admin_only)):
    return await service.search_users(db, q, role, status, verification_status, page, page_size)


@router.get("/users/{user_id}")
async def user_detail(user_id: int, db: AsyncSession = Depends(get_db_async),
                      service: AdminService = Depends(admin_service), user: Users = Depends(admin_only)):
    return await service.user_detail(db, user_id)


@router.put("/users/{user_id}/status")
async def set_user_status(user_id: int, payload: UserStatusSchema, db: AsyncSession = Depends(get_db_async),
                          service: AdminService = Depends(admin_service), user: Users = Depends(admin_only)):
    """Approve (active), deactivate, suspend or reactivate an account. Audited and the user is notified."""
    return await service.set_user_status(db, user.id, user_id, payload.status, payload.reason)


@router.get("/verifications")
async def list_verifications(status: Optional[str] = "PENDING_VERIFICATION", db: AsyncSession = Depends(get_db_async),
                             service: AdminService = Depends(admin_service), user: Users = Depends(admin_only)):
    return await service.list_verifications(db, status)


@router.put("/verifications/{request_id}")
async def review_verification(request_id: int, payload: VerificationDecisionSchema, db: AsyncSession = Depends(get_db_async),
                              service: AdminService = Depends(admin_service), user: Users = Depends(admin_only)):
    return await service.review_verification(db, user.id, request_id, payload.decision, payload.notes)


@router.get("/appeals")
async def list_appeals(status: Optional[str] = "open", db: AsyncSession = Depends(get_db_async),
                       service: AdminService = Depends(admin_service), user: Users = Depends(admin_only)):
    return await service.list_appeals(db, status)


@router.put("/appeals/{appeal_id}")
async def decide_appeal(appeal_id: int, payload: AppealDecisionSchema, db: AsyncSession = Depends(get_db_async),
                        service: AdminService = Depends(admin_service), user: Users = Depends(admin_only)):
    return await service.decide_appeal(db, user.id, appeal_id, payload.accept, payload.notes)


# ---- listings / certifications / reports / reviews ----

@router.get("/listings")
async def list_listings(status: Optional[str] = None, reported_only: bool = False, db: AsyncSession = Depends(get_db_async),
                        service: AdminService = Depends(admin_service), user: Users = Depends(admin_only)):
    return await service.list_listings(db, status, reported_only)


@router.put("/listings/{listing_id}/moderate")
async def moderate_listing(listing_id: int, payload: ListingModerationSchema, db: AsyncSession = Depends(get_db_async),
                           service: AdminService = Depends(admin_service), user: Users = Depends(admin_only)):
    return await service.moderate_listing(db, user.id, listing_id, payload.action, payload.reason)


@router.get("/certifications")
async def list_certifications(status: Optional[str] = "pending", db: AsyncSession = Depends(get_db_async),
                              service: AdminService = Depends(admin_service), user: Users = Depends(admin_only)):
    return await service.list_certifications(db, status)


@router.put("/certifications/{cert_id}")
async def review_certification(cert_id: int, payload: CertificationDecisionSchema, db: AsyncSession = Depends(get_db_async),
                               service: AdminService = Depends(admin_service), user: Users = Depends(admin_only)):
    return await service.review_certification(db, user.id, cert_id, payload.decision, payload.notes)


@router.get("/reports")
async def list_reports(status: Optional[str] = "open", target_type: Optional[str] = None,
                       db: AsyncSession = Depends(get_db_async), service: AdminService = Depends(admin_service),
                       user: Users = Depends(admin_only)):
    return await service.list_reports(db, status, target_type)


@router.put("/reports/{report_id}")
async def decide_report(report_id: int, payload: ReportDecisionSchema, db: AsyncSession = Depends(get_db_async),
                        service: AdminService = Depends(admin_service), user: Users = Depends(admin_only)):
    return await service.decide_report(db, user.id, report_id, payload.decision, payload.notes)


@router.put("/reviews/{review_id}/moderate")
async def moderate_review(review_id: int, payload: ModerateReviewSchema, db: AsyncSession = Depends(get_db_async),
                          user: Users = Depends(admin_only)):
    return await ReviewsService().moderate(review_id, user.id, payload.hidden, payload.reason, db)


# ---- orders / payments ----

@router.get("/orders/{order_id}")
async def order_detail(order_id: int, db: AsyncSession = Depends(get_db_async), user: Users = Depends(admin_only)):
    return await OrdersService().detail(user, order_id, db, is_admin=True)


@router.post("/orders/{order_id}/cancel")
async def cancel_order(order_id: int, reason: str = Query(..., min_length=3),
                       db: AsyncSession = Depends(get_db_async), user: Users = Depends(admin_only)):
    return await OrdersService().cancel(user, order_id, reason, db, role="admin")


@router.post("/orders/{order_id}/adjustments")
async def adjust_order(order_id: int, payload: AdjustmentSchema, db: AsyncSession = Depends(get_db_async),
                       service: AdminService = Depends(admin_service), user: Users = Depends(admin_only)):
    """Correct the payable amount without rewriting the agreed terms. Audited; both parties are notified."""
    return await service.adjust_order(db, user.id, order_id, payload.amount, payload.reason)


@router.post("/orders/{order_id}/refunds")
async def create_refund(order_id: int, payload: RefundSchema, db: AsyncSession = Depends(get_db_async),
                        user: Users = Depends(admin_only)):
    return await PaymentsService().create_refund(user.id, order_id, payload, db)


@router.get("/refunds")
async def list_refunds(status: Optional[str] = None, db: AsyncSession = Depends(get_db_async),
                       service: AdminService = Depends(admin_service), user: Users = Depends(admin_only)):
    return await service.list_refunds(db, status)


@router.post("/refunds/{refund_id}/process")
async def process_refund(refund_id: int, db: AsyncSession = Depends(get_db_async), user: Users = Depends(admin_only)):
    """Send a pending refund of a gateway payment to Razorpay."""
    return await PaymentsService().process_refund(user.id, refund_id, db)


@router.post("/refunds/{refund_id}/mark-refunded")
async def mark_refunded(refund_id: int, payload: MarkRefundedSchema, db: AsyncSession = Depends(get_db_async),
                        user: Users = Depends(admin_only)):
    """Record a refund paid outside the gateway (cash / bank transfer)."""
    return await PaymentsService().mark_refunded(user.id, refund_id, payload.reference, db)


@router.get("/settlements")
async def list_settlements(status: Optional[str] = "pending", db: AsyncSession = Depends(get_db_async),
                           service: AdminService = Depends(admin_service), user: Users = Depends(admin_only)):
    return await service.list_settlements(db, status)


@router.post("/settlements/{settlement_id}/paid")
async def mark_settlement_paid(settlement_id: int, payload: SettlementPayoutSchema, db: AsyncSession = Depends(get_db_async),
                               user: Users = Depends(admin_only)):
    return await PaymentsService().mark_settlement_paid(user.id, settlement_id, payload.payout_reference, db)


@router.post("/payments/reconcile")
async def reconcile_payments(db: AsyncSession = Depends(get_db_async), user: Users = Depends(admin_only)):
    """Check unconfirmed gateway payments against Razorpay and record the real outcome."""
    return await PaymentsService().reconcile(db)


@router.get("/monitoring")
async def monitoring(days: int = Query(30, ge=1, le=365), db: AsyncSession = Depends(get_db_async),
                     service: AdminService = Depends(admin_service), user: Users = Depends(admin_only)):
    """Repeated payment failures, frequent cancellations, stale confirmations, unpaid deliveries, unusual pairs."""
    return await service.monitoring(db, days)


# ---- configuration / announcements / audit ----

@router.get("/settings")
async def get_settings(db: AsyncSession = Depends(get_db_async), service: AdminService = Depends(admin_service),
                       user: Users = Depends(admin_only)):
    return await service.get_settings(db)


@router.put("/settings/{key}")
async def set_setting(key: str, payload: SettingSchema, db: AsyncSession = Depends(get_db_async),
                      service: AdminService = Depends(admin_service), user: Users = Depends(admin_only)):
    """Versioned and audited (fees, expiry defaults, cancellation policy, verification thresholds...)."""
    return await service.set_setting(db, user.id, key, payload.value, payload.reason)


@router.get("/settings/{key}/history")
async def setting_history(key: str, db: AsyncSession = Depends(get_db_async), service: AdminService = Depends(admin_service),
                          user: Users = Depends(admin_only)):
    return await service.settings_history(db, key)


@router.get("/announcements")
async def list_announcements(db: AsyncSession = Depends(get_db_async), service: AdminService = Depends(admin_service),
                             user: Users = Depends(admin_only)):
    return await service.list_announcements(db)


@router.post("/announcements")
async def create_announcement(payload: AnnouncementSchema, db: AsyncSession = Depends(get_db_async),
                              service: AdminService = Depends(admin_service), user: Users = Depends(admin_only)):
    """Announcements and promotional campaigns. Promotional ones only reach users who opted in."""
    return await service.create_announcement(db, user.id, payload)


@router.put("/announcements/{announcement_id}")
async def update_announcement(announcement_id: int, payload: AnnouncementUpdateSchema, db: AsyncSession = Depends(get_db_async),
                              service: AdminService = Depends(admin_service), user: Users = Depends(admin_only)):
    return await service.update_announcement(db, user.id, announcement_id, payload)


@router.get("/audit-logs")
async def audit_logs(actor_id: Optional[int] = None, entity_type: Optional[str] = None, entity_id: Optional[str] = None,
                     action: Optional[str] = None, date_from: Optional[datetime] = None, date_to: Optional[datetime] = None,
                     page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                     db: AsyncSession = Depends(get_db_async), service: AdminService = Depends(admin_service),
                     user: Users = Depends(admin_only)):
    return await service.audit_logs(db, actor_id, entity_type, entity_id, action, date_from, date_to, page, page_size)
