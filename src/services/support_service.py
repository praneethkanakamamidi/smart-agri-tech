
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import audit
from src.data_models.orders_model import Orders
from src.data_models.platform_model import SupportTickets, SupportTicketMessages
from src.helpers.serializers import model_to_dict
from src.services.files_service import FilesService
from src.services.notifications_service import notify_user
from src.core.clock import utcnow


class SupportService:
    async def create(self, user, payload, db: AsyncSession) -> dict:
        if payload.order_id:
            order = (await db.execute(select(Orders).where(Orders.id == payload.order_id))).scalar_one_or_none()
            if not order or user.id not in (order.farmer, order.vendor):
                raise HTTPException(status_code=404, detail="Order not found.")
        files = await FilesService.require_owned(db, payload.file_ids, user.id, {"support_attachment"})
        now = utcnow()
        ticket = SupportTickets(user_id=user.id, subject=payload.subject, category=payload.category, status="open",
                                priority="normal", order_id=payload.order_id, created_at=now, updated_at=now)
        db.add(ticket)
        await db.flush()
        db.add(SupportTicketMessages(ticket_id=ticket.id, author_id=user.id, body=payload.message, file_ids=files,
                                     is_internal=False, created_at=now))
        await db.commit()
        return {"success": "Ticket created. Our team will get back to you.", "ticket_id": ticket.id}

    async def _get(self, db, ticket_id: int, user, is_admin: bool) -> SupportTickets:
        ticket = (await db.execute(select(SupportTickets).where(SupportTickets.id == ticket_id))).scalar_one_or_none()
        if not ticket or (not is_admin and ticket.user_id != user.id):
            raise HTTPException(status_code=404, detail="Ticket not found.")
        return ticket

    async def list_mine(self, user, db: AsyncSession) -> list[dict]:
        rows = (await db.execute(select(SupportTickets).where(SupportTickets.user_id == user.id)
                                 .order_by(SupportTickets.updated_at.desc()))).scalars().all()
        return [model_to_dict(t) for t in rows]

    async def detail(self, ticket_id: int, user, is_admin: bool, db: AsyncSession) -> dict:
        ticket = await self._get(db, ticket_id, user, is_admin)
        stmt = select(SupportTicketMessages).where(SupportTicketMessages.ticket_id == ticket_id)
        if not is_admin:
            stmt = stmt.where(SupportTicketMessages.is_internal.is_(False))
        messages = (await db.execute(stmt.order_by(SupportTicketMessages.id))).scalars().all()
        return {**model_to_dict(ticket), "messages": [
            {**model_to_dict(m), "files": [f"/api/files/{f}" for f in (m.file_ids or [])]} for m in messages
        ]}

    async def reply(self, ticket_id: int, user, is_admin: bool, payload, db: AsyncSession) -> dict:
        ticket = await self._get(db, ticket_id, user, is_admin)
        if ticket.status == "closed":
            raise HTTPException(status_code=409, detail="This ticket is closed. Open a new one.")
        if payload.internal and not is_admin:
            raise HTTPException(status_code=403, detail="Only staff can add internal notes.")
        files = await FilesService.require_owned(db, payload.file_ids, user.id, {"support_attachment"})
        db.add(SupportTicketMessages(ticket_id=ticket.id, author_id=user.id, body=payload.message, file_ids=files,
                                     is_internal=payload.internal, created_at=utcnow()))
        ticket.updated_at = utcnow()
        if is_admin and not payload.internal:
            if ticket.status == "open":
                ticket.status = "in_progress"
            await notify_user(db, ticket.user_id, "ticket_update", {"ticket_id": ticket.id, "status": "new reply"},
                              ref_type="ticket", ref_id=ticket.id)
        elif not is_admin and ticket.status == "resolved":
            ticket.status = "open"
        await db.commit()
        return {"success": "Reply added."}

    async def admin_list(self, db: AsyncSession, status=None, priority=None, assigned_to=None) -> list[dict]:
        stmt = select(SupportTickets)
        if status:
            stmt = stmt.where(SupportTickets.status == status)
        if priority:
            stmt = stmt.where(SupportTickets.priority == priority)
        if assigned_to:
            stmt = stmt.where(SupportTickets.assigned_to == assigned_to)
        return [model_to_dict(t) for t in (await db.execute(stmt.order_by(SupportTickets.updated_at.desc()))).scalars().all()]

    async def admin_update(self, ticket_id: int, admin, payload, db: AsyncSession) -> dict:
        ticket = await self._get(db, ticket_id, admin, True)
        changes = payload.model_dump(exclude_unset=True)
        for key, value in changes.items():
            setattr(ticket, key, value)
        ticket.updated_at = utcnow()
        if changes.get("status") in ("resolved", "closed"):
            ticket.closed_at = utcnow()
            await notify_user(db, ticket.user_id, "ticket_update", {"ticket_id": ticket.id, "status": changes["status"]},
                              ref_type="ticket", ref_id=ticket.id)
        audit(db, "admin.ticket_updated", "support_ticket", ticket.id, actor_id=admin.id, actor_role="admin", after=changes)
        await db.commit()
        return model_to_dict(ticket)
