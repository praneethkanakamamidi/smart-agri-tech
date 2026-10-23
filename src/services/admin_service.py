from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select, func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import audit
from src.core.lookups import misc_id
from src.core.money import money
from src.core.platform_settings import list_settings, update_setting
from src.data_models.crops_model import Crops
from src.data_models.farmer_inventory_model import FarmerInventory, REMOVED, PAUSED
from src.data_models.listing_extras_model import ListingCertifications
from src.data_models.miscellaneous_model import Miscellaneous_Data
from src.data_models.notifications_model import SECURITY, PROMOTIONAL
from src.data_models.orders_model import Orders, OrderAdjustments, CANCELLED, PENDING_CONFIRMATION, DELIVERED
from src.data_models.platform_model import (
    AuditLogs, AccountAppeals, Reports, UserSessions, Announcements, PlatformSettingsHistory,
)
from src.data_models.profiles_model import VerificationRequests
from src.data_models.roles_model import Roles
from src.data_models.transactions_model import Transactions, Refunds, Settlements
from src.data_models.users_model import Users, VERIFIED, REJECTED, PENDING_VERIFICATION, SUSPENDED, UNVERIFIED
from src.helpers.serializers import model_to_dict
from src.services import order_core
from src.services.notifications_service import notify_user
from src.services.trust_service import trust_indicators
from src.services.users_service import UsersService
from src.core.clock import utcnow


def _name(u):
    return f"{u.first_name} {u.last_name}".strip() if u else None


class AdminService:
    # ---- users -----------------------------------------------------------------------

    async def search_users(self, db: AsyncSession, q=None, role=None, status=None, verification_status=None,
                           page: int = 1, page_size: int = 20) -> dict:
        stmt = (
            select(Users, Roles.name, Miscellaneous_Data.value)
            .join(Roles, Users.role_id == Roles.id, isouter=True)
            .join(Miscellaneous_Data, Users.status == Miscellaneous_Data.id, isouter=True)
            .where(Users.deleted_at.is_(None))
        )
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(or_(Users.first_name.ilike(like), Users.last_name.ilike(like), Users.email.ilike(like),
                                  Users.phone.ilike(like), Users.user_name.ilike(like)))
        if role:
            stmt = stmt.where(func.lower(Roles.name) == role.lower())
        if status:
            stmt = stmt.where(Miscellaneous_Data.value == status)
        if verification_status:
            stmt = stmt.where(Users.verification_status == verification_status)
        total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
        rows = (await db.execute(stmt.order_by(Users.id.desc()).limit(page_size).offset((page - 1) * page_size))).all()
        return {
            "page": page, "page_size": page_size, "total_records": total,
            "data": [UsersService._public_user(u, role_name, status_value) for u, role_name, status_value in rows],
        }

    async def user_detail(self, db: AsyncSession, user_id: int) -> dict:
        user = (await db.execute(select(Users).where(Users.id == user_id))).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")
        role = (await db.execute(select(Roles.name).where(Roles.id == user.role_id))).scalar_one_or_none()
        status_value = (await db.execute(select(Miscellaneous_Data.value).where(Miscellaneous_Data.id == user.status))).scalar_one_or_none()
        orders = (await db.execute(
            select(Orders).where(or_(Orders.farmer == user_id, Orders.vendor == user_id))
            .order_by(Orders.created_at.desc()).limit(20)
        )).scalars().all()
        verifications = (await db.execute(select(VerificationRequests).where(VerificationRequests.user_id == user_id))).scalars().all()
        reports = (await db.execute(select(func.count(Reports.id)).where(
            Reports.target_type == "user", Reports.target_id == user_id
        ))).scalar()
        return {
            **UsersService._public_user(user, role, status_value),
            "suspended_reason": user.suspended_reason,
            "mfa_enabled": user.mfa_enabled,
            "last_login_at": user.last_login_at,
            "deletion_requested_at": user.deletion_requested_at,
            "trust": await trust_indicators(db, user_id),
            "reports_against": reports,
            "verifications": [model_to_dict(v) for v in verifications],
            "recent_orders": [
                {"id": o.id, "order_number": o.order_number, "total": o.total_price, "created_at": o.created_at,
                 "role": "farmer" if o.farmer == user_id else "vendor"} for o in orders
            ],
        }

    async def set_user_status(self, db: AsyncSession, admin_id: int, user_id: int, new_status: str, reason: str) -> dict:
        user = (await db.execute(select(Users).where(Users.id == user_id).with_for_update())).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")
        if user_id == admin_id:
            raise HTTPException(status_code=422, detail="You can't change your own account status.")
        before_status = (await db.execute(select(Miscellaneous_Data.value).where(Miscellaneous_Data.id == user.status))).scalar_one_or_none()
        user.status = await misc_id(db, "status", new_status)
        if new_status == "suspended":
            user.suspended_reason = reason
            user.verification_status = SUSPENDED
            await db.execute(update(UserSessions).where(
                UserSessions.user_id == user_id, UserSessions.revoked_at.is_(None)
            ).values(revoked_at=utcnow()))
        elif new_status == "active":
            user.suspended_reason = None
            if user.verification_status == SUSPENDED:
                verified = (await db.execute(select(VerificationRequests.id).where(
                    VerificationRequests.user_id == user_id, VerificationRequests.status == VERIFIED
                ))).first()
                user.verification_status = VERIFIED if verified else UNVERIFIED
        else:
            user.suspended_reason = reason
            await db.execute(update(UserSessions).where(
                UserSessions.user_id == user_id, UserSessions.revoked_at.is_(None)
            ).values(revoked_at=utcnow()))
        await notify_user(db, user_id, "account_status", {"status": new_status, "reason": reason}, category=SECURITY)
        audit(db, "admin.user_status_changed", "user", user_id, actor_id=admin_id, actor_role="admin",
              before={"status": before_status}, after={"status": new_status, "reason": reason})
        await db.commit()
        return {"success": f"User is now {new_status}."}

    # ---- verification --------------------------------------------------------------------

    async def list_verifications(self, db: AsyncSession, status_filter: str | None) -> list[dict]:
        stmt = select(VerificationRequests, Users).join(Users, VerificationRequests.user_id == Users.id)
        if status_filter:
            stmt = stmt.where(VerificationRequests.status == status_filter)
        rows = (await db.execute(stmt.order_by(VerificationRequests.submitted_at))).all()
        return [
            {**model_to_dict(v), "user_name": _name(u), "files": [f"/api/files/{f}" for f in (v.file_ids or [])]}
            for v, u in rows
        ]

    async def review_verification(self, db: AsyncSession, admin_id: int, request_id: int, decision: str, notes: str | None) -> dict:
        request = (await db.execute(select(VerificationRequests).where(VerificationRequests.id == request_id).with_for_update())).scalar_one_or_none()
        if not request or request.status != PENDING_VERIFICATION:
            raise HTTPException(status_code=404, detail="No pending verification request with that id.")
        request.status = decision
        request.reviewer_id = admin_id
        request.review_notes = notes
        request.reviewed_at = utcnow()
        user = (await db.execute(select(Users).where(Users.id == request.user_id))).scalar_one()
        if user.verification_status != SUSPENDED:
            verified_types = set((await db.execute(select(VerificationRequests.verification_type).where(
                VerificationRequests.user_id == user.id, VerificationRequests.status == VERIFIED
            ))).scalars().all())
            if decision == VERIFIED:
                verified_types.add(request.verification_type)
            pending = (await db.execute(select(VerificationRequests.id).where(
                VerificationRequests.user_id == user.id, VerificationRequests.status == PENDING_VERIFICATION,
                VerificationRequests.id != request.id,
            ))).first()
            if "identity" in verified_types:
                user.verification_status = VERIFIED
            elif pending:
                user.verification_status = PENDING_VERIFICATION
            else:
                user.verification_status = REJECTED if decision == REJECTED else UNVERIFIED
        await notify_user(db, user.id, "verification_update",
                          {"kind": request.verification_type, "status": decision}, category=SECURITY)
        audit(db, "admin.verification_reviewed", "verification_request", request.id, actor_id=admin_id,
              actor_role="admin", after={"decision": decision, "notes": notes})
        await db.commit()
        return {"success": f"Verification {decision.lower()}.", "user_verification_status": user.verification_status}

    # ---- appeals -------------------------------------------------------------------------

    async def list_appeals(self, db: AsyncSession, status_filter: str | None) -> list[dict]:
        stmt = select(AccountAppeals, Users).join(Users, AccountAppeals.user_id == Users.id)
        if status_filter:
            stmt = stmt.where(AccountAppeals.status == status_filter)
        rows = (await db.execute(stmt.order_by(AccountAppeals.created_at))).all()
        return [{**model_to_dict(a), "user_name": _name(u), "suspended_reason": u.suspended_reason} for a, u in rows]

    async def decide_appeal(self, db: AsyncSession, admin_id: int, appeal_id: int, accept: bool, notes: str | None) -> dict:
        appeal = (await db.execute(select(AccountAppeals).where(AccountAppeals.id == appeal_id).with_for_update())).scalar_one_or_none()
        if not appeal or appeal.status != "open":
            raise HTTPException(status_code=404, detail="No open appeal with that id.")
        appeal.status = "accepted" if accept else "rejected"
        appeal.reviewed_by = admin_id
        appeal.review_notes = notes
        appeal.reviewed_at = utcnow()
        audit(db, "admin.appeal_decided", "account_appeal", appeal.id, actor_id=admin_id, actor_role="admin",
              after={"accepted": accept, "notes": notes})
        if accept:
            await db.flush()
            return await self.set_user_status(db, admin_id, appeal.user_id, "active", notes or "Appeal accepted")
        await notify_user(db, appeal.user_id, "account_status",
                          {"status": "suspended", "reason": f"Appeal rejected. {notes or ''}"}, category=SECURITY)
        await db.commit()
        return {"success": "Appeal rejected."}

    # ---- listings moderation ----------------------------------------------------------------

    async def list_listings(self, db: AsyncSession, status_filter: str | None, reported_only: bool) -> list[dict]:
        report_counts = (
            select(Reports.target_id, func.count(Reports.id).label("reports"))
            .where(Reports.target_type == "listing", Reports.status == "open")
            .group_by(Reports.target_id).subquery()
        )
        stmt = (
            select(FarmerInventory, Crops.crop_name, Users, report_counts.c.reports)
            .join(Crops, FarmerInventory.crop == Crops.id)
            .join(Users, FarmerInventory.created_by == Users.id)
            .outerjoin(report_counts, report_counts.c.target_id == FarmerInventory.id)
        )
        if status_filter:
            stmt = stmt.where(FarmerInventory.status == status_filter)
        if reported_only:
            stmt = stmt.where(report_counts.c.reports > 0)
        rows = (await db.execute(stmt.order_by(report_counts.c.reports.desc().nullslast(), FarmerInventory.id.desc()).limit(200))).all()
        return [
            {**model_to_dict(l), "crop_name": crop, "farmer_name": _name(u), "open_reports": reports or 0}
            for l, crop, u, reports in rows
        ]

    async def moderate_listing(self, db: AsyncSession, admin_id: int, listing_id: int, action: str, reason: str) -> dict:
        listing = (await db.execute(select(FarmerInventory).where(FarmerInventory.id == listing_id).with_for_update())).scalar_one_or_none()
        if not listing:
            raise HTTPException(status_code=404, detail="Listing not found.")
        before = listing.status
        if action == "remove":
            listing.status = REMOVED
        elif action == "restore":
            if listing.status != REMOVED:
                raise HTTPException(status_code=409, detail="Only removed listings can be restored.")
            listing.status = PAUSED
        listing.moderation_reason = reason
        listing.updated_at = utcnow()
        if action == "remove":
            await db.execute(update(Reports).where(
                Reports.target_type == "listing", Reports.target_id == listing_id, Reports.status == "open"
            ).values(status="actioned", reviewed_by=admin_id, reviewed_at=utcnow(), review_notes=reason))
        crop = (await db.execute(select(Crops.crop_name).where(Crops.id == listing.crop))).scalar_one_or_none()
        await notify_user(db, listing.created_by, "listing_moderated",
                          {"crop": crop, "status": "removed" if action == "remove" else "restored (paused)", "reason": reason},
                          ref_type="listing", ref_id=listing.id)
        audit(db, f"admin.listing_{action}", "listing", listing.id, actor_id=admin_id, actor_role="admin",
              before={"status": before}, after={"status": listing.status, "reason": reason})
        await db.commit()
        return {"success": f"Listing {listing.status}."}

    async def list_certifications(self, db: AsyncSession, status_filter: str | None) -> list[dict]:
        stmt = select(ListingCertifications)
        if status_filter:
            stmt = stmt.where(ListingCertifications.status == status_filter)
        rows = (await db.execute(stmt.order_by(ListingCertifications.created_at))).scalars().all()
        return [{**model_to_dict(c), "file_url": f"/api/files/{c.file_id}" if c.file_id else None} for c in rows]

    async def review_certification(self, db: AsyncSession, admin_id: int, cert_id: int, decision: str, notes: str | None) -> dict:
        cert = (await db.execute(select(ListingCertifications).where(ListingCertifications.id == cert_id).with_for_update())).scalar_one_or_none()
        if not cert or cert.status != "pending":
            raise HTTPException(status_code=404, detail="No pending certification with that id.")
        cert.status = decision
        cert.reviewed_by = admin_id
        cert.review_notes = notes
        cert.reviewed_at = utcnow()
        if cert.cert_type == "organic":
            listing = (await db.execute(select(FarmerInventory).where(FarmerInventory.id == cert.listing_id))).scalar_one()
            listing.organic_verified = decision == "verified" and listing.organic_claim
        audit(db, "admin.certification_reviewed", "listing_certification", cert.id, actor_id=admin_id,
              actor_role="admin", after={"decision": decision})
        await db.commit()
        return {"success": f"Certification {decision}."}

    # ---- reports & reviews ---------------------------------------------------------------------

    async def list_reports(self, db: AsyncSession, status_filter: str | None, target_type: str | None) -> list[dict]:
        stmt = select(Reports)
        if status_filter:
            stmt = stmt.where(Reports.status == status_filter)
        if target_type:
            stmt = stmt.where(Reports.target_type == target_type)
        return [model_to_dict(r) for r in (await db.execute(stmt.order_by(Reports.created_at))).scalars().all()]

    async def decide_report(self, db: AsyncSession, admin_id: int, report_id: int, decision: str, notes: str | None) -> dict:
        report = (await db.execute(select(Reports).where(Reports.id == report_id))).scalar_one_or_none()
        if not report or report.status != "open":
            raise HTTPException(status_code=404, detail="No open report with that id.")
        report.status = decision
        report.reviewed_by = admin_id
        report.review_notes = notes
        report.reviewed_at = utcnow()
        audit(db, "admin.report_decided", "report", report.id, actor_id=admin_id, actor_role="admin",
              after={"decision": decision, "notes": notes})
        await db.commit()
        return {"success": f"Report {decision}."}

    # ---- orders & money --------------------------------------------------------------------------

    async def adjust_order(self, db: AsyncSession, admin_id: int, order_id: int, amount: float, reason: str) -> dict:
        """Authorised correction. The agreed terms are untouched; the adjustment is a separate, audited record."""
        order = await order_core.lock_order(db, order_id)
        adjustment = OrderAdjustments(order_id=order.id, amount=money(amount), reason=reason, created_by=admin_id,
                                      created_at=utcnow())
        db.add(adjustment)
        for party_id in (order.farmer, order.vendor):
            await notify_user(db, party_id, "order_adjustment",
                              {"order_number": order.order_number, "amount": money(amount), "reason": reason},
                              ref_type="order", ref_id=order.id)
        audit(db, "admin.order_adjusted", "order", order.id, actor_id=admin_id, actor_role="admin",
              before={"total_price": order.total_price}, after={"adjustment": money(amount), "reason": reason})
        await db.commit()
        return {"success": "Adjustment recorded and both parties notified.",
                "money": await order_core.money_summary(db, order)}

    async def list_refunds(self, db: AsyncSession, status_filter: str | None) -> list[dict]:
        stmt = select(Refunds, Orders.order_number).join(Orders, Refunds.order_id == Orders.id)
        if status_filter:
            stmt = stmt.where(Refunds.status == status_filter)
        return [model_to_dict(r, order_number=n) for r, n in (await db.execute(stmt.order_by(Refunds.created_at))).all()]

    async def list_settlements(self, db: AsyncSession, status_filter: str | None) -> list[dict]:
        stmt = select(Settlements, Orders.order_number, Users).join(Orders, Settlements.order_id == Orders.id) \
            .join(Users, Settlements.farmer == Users.id)
        if status_filter:
            stmt = stmt.where(Settlements.status == status_filter)
        return [model_to_dict(s, order_number=n, farmer_name=_name(u))
                for s, n, u in (await db.execute(stmt.order_by(Settlements.created_at))).all()]

    async def monitoring(self, db: AsyncSession, days: int = 30) -> dict:
        since = utcnow() - timedelta(days=days)
        failed_id = await misc_id(db, "payment_status", "failed")
        failed_by_vendor = (await db.execute(
            select(Orders.vendor, func.count(Transactions.id))
            .join(Orders, Transactions.order_id == Orders.id)
            .where(Transactions.status == failed_id, Transactions.created_at >= since)
            .group_by(Orders.vendor).having(func.count(Transactions.id) >= 3)
        )).all()
        cancelled_id = await misc_id(db, "order_status", CANCELLED)
        cancellations = (await db.execute(
            select(Orders.cancelled_by, func.count(Orders.id))
            .where(Orders.status == cancelled_id, Orders.cancelled_at >= since, Orders.cancelled_by.is_not(None))
            .group_by(Orders.cancelled_by).having(func.count(Orders.id) >= 3)
        )).all()
        pending_id = await misc_id(db, "order_status", PENDING_CONFIRMATION)
        stale_confirmations = (await db.execute(select(func.count(Orders.id)).where(
            Orders.status == pending_id, Orders.confirmation_deadline < utcnow()
        ))).scalar()
        delivered_id = await misc_id(db, "order_status", DELIVERED)
        delivered_unpaid = []
        for order in (await db.execute(select(Orders).where(Orders.status == delivered_id).limit(500))).scalars().all():
            summary = await order_core.money_summary(db, order)
            if summary["outstanding"] > 0:
                delivered_unpaid.append({"order_id": order.id, "order_number": order.order_number,
                                         "outstanding": summary["outstanding"], "delivered_at": order.delivered_at})
        self_dealing = (await db.execute(
            select(Orders.farmer, Orders.vendor, func.count(Orders.id))
            .where(Orders.created_at >= since).group_by(Orders.farmer, Orders.vendor).having(func.count(Orders.id) >= 10)
        )).all()
        return {
            "period_days": days,
            "vendors_with_repeated_payment_failures": [{"vendor_id": v, "failures": c} for v, c in failed_by_vendor],
            "users_with_frequent_cancellations": [{"user_id": u, "cancellations": c} for u, c in cancellations],
            "orders_past_confirmation_deadline": stale_confirmations,
            "delivered_orders_with_outstanding_payment": delivered_unpaid,
            "unusually_frequent_pairs": [{"farmer_id": f, "vendor_id": v, "orders": c} for f, v, c in self_dealing],
            "pending_refunds": (await db.execute(select(func.count(Refunds.id)).where(Refunds.status == "REFUND_PENDING"))).scalar(),
            "open_reports": (await db.execute(select(func.count(Reports.id)).where(Reports.status == "open"))).scalar(),
        }

    # ---- settings, announcements, audit ------------------------------------------------------------

    async def get_settings(self, db: AsyncSession) -> list[dict]:
        return await list_settings(db)

    async def set_setting(self, db: AsyncSession, admin_id: int, key: str, value, reason: str | None) -> dict:
        change = await update_setting(db, key, value, admin_id, reason)
        audit(db, "admin.setting_changed", "platform_setting", key, actor_id=admin_id, actor_role="admin",
              before={"value": change["before"]}, after={"value": change["after"], "version": change["version"], "reason": reason})
        await db.commit()
        return change

    async def settings_history(self, db: AsyncSession, key: str) -> list[dict]:
        rows = (await db.execute(select(PlatformSettingsHistory).where(PlatformSettingsHistory.key == key)
                                 .order_by(PlatformSettingsHistory.version.desc()))).scalars().all()
        return [model_to_dict(r) for r in rows]

    async def create_announcement(self, db: AsyncSession, admin_id: int, payload) -> dict:
        row = Announcements(**payload.model_dump(exclude={"notify"}), created_by=admin_id, created_at=utcnow())
        db.add(row)
        await db.flush()
        notified = 0
        if payload.notify:
            notified = await self._broadcast(db, row)
        audit(db, "admin.announcement_created", "announcement", row.id, actor_id=admin_id, actor_role="admin",
              after=payload.model_dump())
        await db.commit()
        return {"success": "Announcement created.", "id": row.id, "notified_users": notified}

    async def _broadcast(self, db: AsyncSession, row: Announcements) -> int:
        stmt = select(Users.id, Users.preferred_language).join(Roles, Users.role_id == Roles.id).where(Users.deleted_at.is_(None))
        if row.audience in ("farmer", "vendor"):
            stmt = stmt.where(func.lower(Roles.name) == row.audience)
        count = 0
        for user_id, lang in (await db.execute(stmt)).all():
            title = row.title_te if lang == "te" and row.title_te else row.title
            body = row.body_te if lang == "te" and row.body_te else row.body
            created = await notify_user(db, user_id, "announcement", {"title": title, "body": body[:400]},
                                        ref_type="announcement", ref_id=row.id,
                                        category=PROMOTIONAL if row.is_promotional else "transactional",
                                        dedupe_key=f"announcement:{row.id}")
            count += 1 if created else 0
        row.notified_at = utcnow()
        return count

    async def update_announcement(self, db: AsyncSession, admin_id: int, announcement_id: int, payload) -> dict:
        row = (await db.execute(select(Announcements).where(Announcements.id == announcement_id))).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Announcement not found.")
        for key, value in payload.model_dump(exclude_unset=True, exclude={"notify"}).items():
            setattr(row, key, value)
        audit(db, "admin.announcement_updated", "announcement", row.id, actor_id=admin_id, actor_role="admin",
              after=payload.model_dump(exclude_unset=True))
        await db.commit()
        return model_to_dict(row)

    async def list_announcements(self, db: AsyncSession) -> list[dict]:
        return [model_to_dict(a) for a in (await db.execute(select(Announcements).order_by(Announcements.created_at.desc()))).scalars().all()]

    async def audit_logs(self, db: AsyncSession, actor_id=None, entity_type=None, entity_id=None, action=None,
                         date_from=None, date_to=None, page: int = 1, page_size: int = 50) -> dict:
        stmt = select(AuditLogs)
        if actor_id:
            stmt = stmt.where(AuditLogs.actor_id == actor_id)
        if entity_type:
            stmt = stmt.where(AuditLogs.entity_type == entity_type)
        if entity_id:
            stmt = stmt.where(AuditLogs.entity_id == str(entity_id))
        if action:
            stmt = stmt.where(AuditLogs.action.ilike(f"{action}%"))
        if date_from:
            stmt = stmt.where(AuditLogs.created_at >= date_from)
        if date_to:
            stmt = stmt.where(AuditLogs.created_at <= date_to)
        total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
        rows = (await db.execute(stmt.order_by(AuditLogs.id.desc()).limit(page_size).offset((page - 1) * page_size))).scalars().all()
        return {"page": page, "page_size": page_size, "total_records": total, "data": [model_to_dict(r) for r in rows]}


async def active_announcements(db: AsyncSession, role: str | None, lang: str) -> list[dict]:
    now = utcnow()
    stmt = select(Announcements).where(
        Announcements.is_active.is_(True),
        or_(Announcements.starts_at.is_(None), Announcements.starts_at <= now),
        or_(Announcements.ends_at.is_(None), Announcements.ends_at >= now),
        Announcements.audience.in_(("all", role or "all")),
    ).order_by(Announcements.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {"id": a.id, "title": a.title_te if lang == "te" and a.title_te else a.title,
         "body": a.body_te if lang == "te" and a.body_te else a.body, "is_promotional": a.is_promotional,
         "starts_at": a.starts_at, "ends_at": a.ends_at}
        for a in rows
    ]
