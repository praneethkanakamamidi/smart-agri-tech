from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select, or_, func
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import audit
from src.core.money import money
from src.core.platform_settings import get_setting
from src.data_models.disputes_model import (
    Disputes, DisputeMessages, OPEN, UNDER_REVIEW, AWAITING_EVIDENCE, RESOLVED, WITHDRAWN,
    ACTIVE_DISPUTE_STATES,
)
from src.data_models.orders_model import (
    Orders, CONFIRMED, PREPARING, READY_FOR_PICKUP, IN_TRANSIT, DELIVERED, COMPLETED, DELIVERY_FAILED, DISPUTED,
    CANCELLED, REFUND_PENDING, REFUNDED,
)
from src.data_models.roles_model import Roles
from src.data_models.users_model import Users
from src.helpers.serializers import model_to_dict
from src.services import order_core
from src.services.files_service import FilesService
from src.services.notifications_service import notify_user
from src.core.clock import utcnow

DISPUTABLE = (CONFIRMED, PREPARING, READY_FOR_PICKUP, IN_TRANSIT, DELIVERED, COMPLETED, DELIVERY_FAILED,
              CANCELLED, REFUND_PENDING, REFUNDED)
# Orders in these states are moved to DISPUTED while the case is open.
FREEZE_ORDER = (IN_TRANSIT, DELIVERED, COMPLETED, DELIVERY_FAILED)


def _name(user):
    return f"{user.first_name} {user.last_name}".strip() if user else None


class DisputesService:
    _options = (joinedload(Disputes.raised_by_user), joinedload(Disputes.against_user))

    def _view(self, dispute: Disputes) -> dict:
        return model_to_dict(dispute, raised_by_name=_name(dispute.raised_by_user),
                             against_name=_name(dispute.against_user))

    async def _admin_ids(self, db: AsyncSession) -> list[int]:
        return (await db.execute(
            select(Users.id).join(Roles, Users.role_id == Roles.id).where(func.lower(Roles.name) == "admin")
        )).scalars().all()

    async def _get(self, db: AsyncSession, dispute_id: int, user_id: int, is_admin: bool, lock: bool = False) -> Disputes:
        stmt = select(Disputes).where(Disputes.id == dispute_id)
        if lock:
            stmt = stmt.with_for_update()
        dispute = (await db.execute(stmt)).scalar_one_or_none()
        if not dispute or (not is_admin and user_id not in (dispute.raised_by, dispute.against)):
            raise HTTPException(status_code=404, detail="Dispute not found.")
        return dispute

    def _log(self, db, dispute_id: int, author_id: int | None, body: str, kind: str, file_ids=None):
        db.add(DisputeMessages(dispute_id=dispute_id, author_id=author_id, body=body[:2000], file_ids=file_ids or [],
                               kind=kind, created_at=utcnow()))

    async def raise_dispute(self, payload, user_id: int, db: AsyncSession):
        order = await order_core.lock_order(db, payload.order_id)
        if user_id not in (order.farmer, order.vendor):
            raise HTTPException(status_code=404, detail="Order not found.")
        current = await order_core.status_of(db, order)
        if current not in DISPUTABLE:
            raise HTTPException(status_code=409, detail=f"Disputes can't be raised on a {current} order.")
        window = int(await get_setting(db, "dispute_window_days"))
        if order.delivered_at and order.delivered_at < utcnow() - timedelta(days=window):
            raise HTTPException(status_code=409, detail=f"Disputes must be raised within {window} days of delivery.")
        if (await db.execute(select(Disputes.id).where(
            Disputes.order_id == order.id, Disputes.status.in_(ACTIVE_DISPUTE_STATES)
        ))).first():
            raise HTTPException(status_code=409, detail="This order already has an open dispute.")
        evidence = await FilesService.require_owned(db, payload.evidence_file_ids, user_id, {"dispute_evidence"})

        against = order.vendor if user_id == order.farmer else order.farmer
        now = utcnow()
        dispute = Disputes(order_id=order.id, raised_by=user_id, against=against, reason=payload.reason,
                           description=payload.description, status=OPEN, escalated=False,
                           created_at=now, updated_at=now)
        db.add(dispute)
        await db.flush()
        self._log(db, dispute.id, user_id, payload.description or payload.reason, "evidence" if evidence else "message", evidence)
        if current in FREEZE_ORDER:
            order.status_before_dispute = current
            await order_core.transition(db, order, DISPUTED, None, note=f"dispute #{dispute.id}: {payload.reason}",
                                        skip_payment_gate=True)
        params = {"order_number": order.order_number, "reason": payload.reason.replace("_", " ")}
        await notify_user(db, against, "dispute_raised", params, ref_type="dispute", ref_id=dispute.id)
        for admin_id in await self._admin_ids(db):
            await notify_user(db, admin_id, "dispute_raised", params, ref_type="dispute", ref_id=dispute.id)
        audit(db, "dispute.raised", "dispute", dispute.id, actor_id=user_id, after={"order_id": order.id, "reason": payload.reason})
        await db.commit()
        return {"success": "Dispute raised. The other party and our team have been notified.", "dispute_id": dispute.id}

    async def add_message(self, dispute_id: int, payload, user_id: int, is_admin: bool, db: AsyncSession) -> dict:
        dispute = await self._get(db, dispute_id, user_id, is_admin)
        if dispute.status not in ACTIVE_DISPUTE_STATES:
            raise HTTPException(status_code=409, detail="This dispute is closed.")
        if payload.internal and not is_admin:
            raise HTTPException(status_code=403, detail="Only admins can add internal notes.")
        evidence = await FilesService.require_owned(db, payload.evidence_file_ids, user_id, {"dispute_evidence"})
        kind = "internal_note" if payload.internal else ("evidence" if evidence else "message")
        self._log(db, dispute.id, user_id, payload.body, kind, evidence)
        dispute.updated_at = utcnow()
        if not payload.internal:
            if dispute.status == AWAITING_EVIDENCE and not is_admin:
                dispute.status = UNDER_REVIEW
            recipients = {dispute.raised_by, dispute.against, dispute.assigned_to} - {user_id, None}
            for party_id in recipients:
                await notify_user(db, party_id, "dispute_update", {"dispute_id": dispute.id, "status": dispute.status},
                                  ref_type="dispute", ref_id=dispute.id)
        await db.commit()
        return {"success": "Added to the case."}

    async def get(self, dispute_id: int, user_id: int, is_admin: bool, db: AsyncSession) -> dict:
        dispute = (await db.execute(select(Disputes).where(Disputes.id == dispute_id).options(*self._options))).scalar_one_or_none()
        if not dispute or (not is_admin and user_id not in (dispute.raised_by, dispute.against)):
            raise HTTPException(status_code=404, detail="Dispute not found.")
        stmt = select(DisputeMessages).where(DisputeMessages.dispute_id == dispute_id).order_by(DisputeMessages.id)
        if not is_admin:
            stmt = stmt.where(DisputeMessages.kind != "internal_note")
        history = (await db.execute(stmt)).scalars().all()
        return {
            **self._view(dispute),
            "history": [
                {**model_to_dict(m), "files": [f"/api/files/{f}" for f in (m.file_ids or [])]}
                for m in history
            ],
        }

    async def withdraw(self, dispute_id: int, user_id: int, db: AsyncSession) -> dict:
        dispute = await self._get(db, dispute_id, user_id, False, lock=True)
        if dispute.raised_by != user_id or dispute.status not in ACTIVE_DISPUTE_STATES:
            raise HTTPException(status_code=409, detail="Only the person who raised an open dispute can withdraw it.")
        dispute.status = WITHDRAWN
        dispute.resolved_at = dispute.updated_at = utcnow()
        await self._restore_order(db, dispute, f"dispute #{dispute.id} withdrawn")
        self._log(db, dispute.id, user_id, "Dispute withdrawn.", "status_change")
        await notify_user(db, dispute.against, "dispute_update", {"dispute_id": dispute.id, "status": WITHDRAWN},
                          ref_type="dispute", ref_id=dispute.id)
        audit(db, "dispute.withdrawn", "dispute", dispute.id, actor_id=user_id)
        await db.commit()
        return {"success": "Dispute withdrawn."}

    async def escalate(self, dispute_id: int, user_id: int, db: AsyncSession) -> dict:
        dispute = await self._get(db, dispute_id, user_id, False, lock=True)
        if dispute.status not in ACTIVE_DISPUTE_STATES:
            raise HTTPException(status_code=409, detail="This dispute is closed.")
        if dispute.escalated:
            return {"success": "This dispute is already escalated."}
        if dispute.created_at > utcnow() - timedelta(days=2):
            raise HTTPException(status_code=409, detail="You can escalate if the dispute is still unresolved after 2 days.")
        dispute.escalated = True
        dispute.escalated_at = dispute.updated_at = utcnow()
        self._log(db, dispute.id, user_id, "Dispute escalated for priority review.", "status_change")
        order = (await db.execute(select(Orders).where(Orders.id == dispute.order_id))).scalar_one()
        for admin_id in await self._admin_ids(db):
            await notify_user(db, admin_id, "dispute_update", {"dispute_id": dispute.id, "status": "escalated"},
                              ref_type="dispute", ref_id=dispute.id)
        audit(db, "dispute.escalated", "dispute", dispute.id, actor_id=user_id, after={"order": order.order_number})
        await db.commit()
        return {"success": "Dispute escalated."}

    async def list_my_disputes(self, user_id: int, db: AsyncSession):
        rows = (await db.execute(
            select(Disputes).where(or_(Disputes.raised_by == user_id, Disputes.against == user_id))
            .options(*self._options).order_by(Disputes.created_at.desc())
        )).scalars().unique().all()
        return [self._view(d) for d in rows]

    # ---- admin --------------------------------------------------------------------

    async def list_all_disputes(self, db: AsyncSession, status_filter: str = None, escalated: bool | None = None,
                                assigned_to: int | None = None):
        stmt = select(Disputes).options(*self._options).order_by(Disputes.escalated.desc(), Disputes.created_at.asc())
        if status_filter:
            stmt = stmt.where(Disputes.status == status_filter)
        if escalated is not None:
            stmt = stmt.where(Disputes.escalated.is_(escalated))
        if assigned_to:
            stmt = stmt.where(Disputes.assigned_to == assigned_to)
        return [self._view(d) for d in (await db.execute(stmt)).scalars().unique().all()]

    async def assign(self, dispute_id: int, admin_id: int, assignee_id: int, db: AsyncSession) -> dict:
        dispute = await self._get(db, dispute_id, admin_id, True, lock=True)
        if assignee_id not in await self._admin_ids(db):
            raise HTTPException(status_code=422, detail="Disputes can only be assigned to admins.")
        dispute.assigned_to = assignee_id
        if dispute.status == OPEN:
            dispute.status = UNDER_REVIEW
        dispute.updated_at = utcnow()
        self._log(db, dispute.id, admin_id, f"Assigned to admin #{assignee_id}.", "status_change")
        audit(db, "dispute.assigned", "dispute", dispute.id, actor_id=admin_id, actor_role="admin", after={"assigned_to": assignee_id})
        await db.commit()
        return {"success": "Dispute assigned."}

    async def set_status(self, dispute_id: int, admin_id: int, payload, db: AsyncSession) -> dict:
        dispute = await self._get(db, dispute_id, admin_id, True, lock=True)
        if dispute.status not in ACTIVE_DISPUTE_STATES:
            raise HTTPException(status_code=409, detail="This dispute is closed.")
        before = dispute.status
        dispute.status = payload.status
        dispute.updated_at = utcnow()
        self._log(db, dispute.id, admin_id, payload.note or f"Status changed to {payload.status}.", "status_change")
        for party_id in (dispute.raised_by, dispute.against):
            await notify_user(db, party_id, "dispute_update", {"dispute_id": dispute.id, "status": payload.status},
                              ref_type="dispute", ref_id=dispute.id)
        audit(db, "dispute.status_changed", "dispute", dispute.id, actor_id=admin_id, actor_role="admin",
              before={"status": before}, after={"status": payload.status})
        await db.commit()
        return {"success": f"Dispute is now {payload.status}."}

    async def _restore_order(self, db: AsyncSession, dispute: Disputes, note: str):
        order = await order_core.lock_order(db, dispute.order_id)
        if await order_core.status_of(db, order) == DISPUTED:
            previous = order.status_before_dispute or DELIVERED
            target = COMPLETED if previous == COMPLETED else DELIVERED
            if previous in (IN_TRANSIT, DELIVERY_FAILED):
                target = DELIVERED  # admin decided the delivery stands
            await order_core.transition(db, order, target, None, note=note, skip_payment_gate=True)
        return order

    async def resolve_dispute(self, dispute_id: int, payload, admin_id: int, db: AsyncSession):
        """
        Record the decision. Refunds are separate refund records - historical payments are never edited.
        """
        dispute = await self._get(db, dispute_id, admin_id, True, lock=True)
        if dispute.status not in ACTIVE_DISPUTE_STATES:
            raise HTTPException(status_code=400, detail=f"Dispute is already {dispute.status}.")
        order = await order_core.lock_order(db, dispute.order_id)
        refund = None
        if payload.status == RESOLVED and payload.resolution_type in ("full_refund", "partial_refund"):
            summary = await order_core.money_summary(db, order)
            refundable = summary["paid"] - summary["refunded"] - summary["refund_pending"]
            amount = refundable if payload.resolution_type == "full_refund" else money(payload.refund_amount or 0)
            if payload.resolution_type == "partial_refund" and not payload.refund_amount:
                raise HTTPException(status_code=422, detail="refund_amount is required for a partial refund.")
            if amount > 0:
                if payload.resolution_type == "partial_refund":
                    await self._restore_order(db, dispute, f"dispute #{dispute.id} resolved with partial refund")
                refund = await order_core.refund_if_paid(db, order, admin_id, f"dispute #{dispute.id}: {payload.resolution}",
                                                         amount, dispute_id=dispute.id)
            elif payload.resolution_type == "full_refund" and await order_core.status_of(db, order) == DISPUTED:
                await order_core.transition(db, order, CANCELLED, admin_id, "admin",
                                            note=f"dispute #{dispute.id}: nothing paid, order cancelled",
                                            skip_payment_gate=True)
        else:
            await self._restore_order(db, dispute, f"dispute #{dispute.id} {payload.status}")

        dispute.status = payload.status
        dispute.resolution = payload.resolution
        dispute.resolution_type = payload.resolution_type
        dispute.refund_amount = str(refund.amount) if refund else None
        dispute.resolved_by = admin_id
        dispute.resolved_at = dispute.updated_at = utcnow()
        self._log(db, dispute.id, admin_id, f"{payload.status.title()}: {payload.resolution}", "status_change")
        for party in (dispute.raised_by, dispute.against):
            await notify_user(db, party, "dispute_resolved",
                              {"dispute_id": dispute.id, "status": payload.status, "resolution": payload.resolution[:200]},
                              ref_type="dispute", ref_id=dispute.id)
        audit(db, "dispute.resolved", "dispute", dispute.id, actor_id=admin_id, actor_role="admin",
              after={"status": payload.status, "resolution_type": payload.resolution_type,
                     "refund_id": refund.id if refund else None})
        await db.commit()
        return {"success": f"Dispute {payload.status}.", "refund_id": refund.id if refund else None}
