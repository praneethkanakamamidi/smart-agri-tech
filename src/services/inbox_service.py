from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select, func, case, update, and_, or_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.platform_settings import get_setting
from src.core.rate_limit import limiter
from src.core.realtime import queue_event
from src.data_models.disputes_model import Disputes
from src.data_models.farmer_inventory_model import FarmerInventory
from src.data_models.market_offers_model import MarketOffers
from src.data_models.messages_model import Messages
from src.data_models.negotiation_model import Negotiations
from src.data_models.orders_model import Orders
from src.data_models.platform_model import UserBlocks, Reports
from src.data_models.users_model import Users
from src.helpers.serializers import model_to_dict
from src.services.files_service import FilesService
from src.services.negotiations_service import ensure_not_blocked
from src.services.notifications_service import notify_user


class InboxService:
    """One-to-one messages between farmers and vendors, linked to the deal they are about."""

    async def _check_context(self, db: AsyncSession, payload, parties: set[int]):
        if payload.offer_id is not None:
            offer = (await db.execute(select(MarketOffers).where(MarketOffers.id == payload.offer_id))).scalar_one_or_none()
            if not offer or {offer.farmer, offer.vendor} != parties:
                raise HTTPException(status_code=404, detail="Offer not found for this conversation.")
        if payload.negotiation_id is not None:
            n = (await db.execute(select(Negotiations).where(Negotiations.id == payload.negotiation_id))).scalar_one_or_none()
            if not n or {n.farmer, n.vendor} != parties:
                raise HTTPException(status_code=404, detail="Negotiation not found for this conversation.")
        if payload.order_id is not None:
            o = (await db.execute(select(Orders).where(Orders.id == payload.order_id))).scalar_one_or_none()
            if not o or {o.farmer, o.vendor} != parties:
                raise HTTPException(status_code=404, detail="Order not found for this conversation.")
        if payload.dispute_id is not None:
            d = (await db.execute(select(Disputes).where(Disputes.id == payload.dispute_id))).scalar_one_or_none()
            if not d or {d.raised_by, d.against} != parties:
                raise HTTPException(status_code=404, detail="Dispute not found for this conversation.")
        if payload.listing_id is not None:
            l = (await db.execute(select(FarmerInventory).where(FarmerInventory.id == payload.listing_id))).scalar_one_or_none()
            if not l or l.created_by not in parties:
                raise HTTPException(status_code=404, detail="Listing not found for this conversation.")

    async def send_message(self, payload, sender_id: int, db: AsyncSession):
        limit = int(await get_setting(db, "message_rate_per_minute"))
        limiter.check(f"msg:{sender_id}", limit, 60)
        body = (payload.body or "").strip()
        if not body and not payload.attachment_file_id:
            raise HTTPException(status_code=422, detail="Message body cannot be empty.")
        if payload.receiver_id == sender_id:
            raise HTTPException(status_code=422, detail="You cannot message yourself.")
        receiver = (await db.execute(select(Users).where(Users.id == payload.receiver_id))).scalar_one_or_none()
        if not receiver or receiver.deleted_at:
            raise HTTPException(status_code=404, detail="Receiver not found.")
        await ensure_not_blocked(db, sender_id, payload.receiver_id)
        await self._check_context(db, payload, {sender_id, payload.receiver_id})
        if payload.attachment_file_id:
            await FilesService.require_owned(db, [payload.attachment_file_id], sender_id, {"chat_attachment"})

        message = Messages(
            sender=sender_id, receiver=payload.receiver_id, offer_id=payload.offer_id, order_id=payload.order_id,
            listing_id=payload.listing_id, negotiation_id=payload.negotiation_id, dispute_id=payload.dispute_id,
            attachment_file_id=payload.attachment_file_id,
            message_type="image" if payload.attachment_file_id else "text",
            body=body or "[attachment]", is_read=False, created_at=datetime.utcnow(),
        )
        db.add(message)
        await db.flush()
        if payload.listing_id:
            await db.execute(update(FarmerInventory).where(FarmerInventory.id == payload.listing_id)
                             .values(inquiries_count=FarmerInventory.inquiries_count + 1))
        sender = (await db.execute(select(Users).where(Users.id == sender_id))).scalar_one()
        await notify_user(db, payload.receiver_id, "new_message",
                          {"party": f"{sender.first_name} {sender.last_name}".strip(), "preview": message.body[:120]},
                          ref_type="message", ref_id=message.id)
        queue_event(db, payload.receiver_id, {"event": "message", "message": model_to_dict(message)})
        await db.commit()
        return {"success": "Message sent.", "message_id": message.id}

    async def get_conversations(self, user_id: int, db: AsyncSession):
        other_party = case((Messages.sender == user_id, Messages.receiver), else_=Messages.sender).label("other_party")
        ranked = (
            select(
                Messages.id, other_party,
                func.row_number().over(partition_by=other_party,
                                       order_by=(Messages.created_at.desc(), Messages.id.desc())).label("rn"),
            )
            .where(or_(Messages.sender == user_id, Messages.receiver == user_id))
            .subquery()
        )
        latest_rows = (await db.execute(
            select(Messages, ranked.c.other_party).join(ranked, Messages.id == ranked.c.id)
            .where(ranked.c.rn == 1).order_by(Messages.created_at.desc())
        )).all()
        unread = dict((await db.execute(
            select(Messages.sender, func.count(Messages.id))
            .where(Messages.receiver == user_id, Messages.is_read.is_(False)).group_by(Messages.sender)
        )).all())
        other_ids = [row.other_party for row in latest_rows]
        users = {u.id: u for u in (await db.execute(select(Users).where(Users.id.in_(other_ids)))).scalars().all()} if other_ids else {}
        blocked = set((await db.execute(select(UserBlocks.blocked_id).where(UserBlocks.blocker_id == user_id))).scalars().all())
        return [
            {
                "user_id": other_id,
                "user_name": f"{users[other_id].first_name} {users[other_id].last_name}".strip() if other_id in users else None,
                "last_message": message.body,
                "last_message_type": message.message_type,
                "last_message_at": message.created_at,
                "last_message_from_me": message.sender == user_id,
                "unread_count": unread.get(other_id, 0),
                "blocked_by_me": other_id in blocked,
            }
            for message, other_id in latest_rows
        ]

    async def get_thread(self, user_id: int, other_id: int, db: AsyncSession, page: int = 1, page_size: int = 50,
                         negotiation_id: int | None = None, order_id: int | None = None, listing_id: int | None = None):
        """Messages with one user (optionally only those about one negotiation/order/listing). Marks them read."""
        between = or_(
            and_(Messages.sender == user_id, Messages.receiver == other_id),
            and_(Messages.sender == other_id, Messages.receiver == user_id),
        )
        filters = [between]
        if negotiation_id:
            filters.append(Messages.negotiation_id == negotiation_id)
        if order_id:
            filters.append(Messages.order_id == order_id)
        if listing_id:
            filters.append(Messages.listing_id == listing_id)
        total_records = (await db.execute(select(func.count(Messages.id)).where(*filters))).scalar() or 0
        messages = list(reversed((await db.execute(
            select(Messages).where(*filters).order_by(Messages.created_at.desc(), Messages.id.desc())
            .limit(page_size).offset((page - 1) * page_size)
        )).scalars().all()))
        data = []
        for m in messages:
            item = model_to_dict(m, is_mine=m.sender == user_id)
            item["attachment_url"] = f"/api/files/{m.attachment_file_id}" if m.attachment_file_id else None
            data.append(item)
        await db.execute(update(Messages).where(
            Messages.sender == other_id, Messages.receiver == user_id, Messages.is_read.is_(False)
        ).values(is_read=True))
        queue_event(db, other_id, {"event": "messages_read", "by_user_id": user_id})
        await db.commit()
        return {"page": page, "page_size": page_size, "total_records": total_records,
                "total_pages": (total_records + page_size - 1) // page_size, "data": data}

    async def unread_count(self, user_id: int, db: AsyncSession):
        stmt = select(func.count(Messages.id)).where(Messages.receiver == user_id, Messages.is_read.is_(False))
        return {"unread_count": (await db.execute(stmt)).scalar() or 0}

    # ---- safety ------------------------------------------------------------------------

    async def block(self, user_id: int, other_id: int, db: AsyncSession) -> dict:
        if user_id == other_id:
            raise HTTPException(status_code=422, detail="You can't block yourself.")
        if not (await db.execute(select(Users.id).where(Users.id == other_id))).first():
            raise HTTPException(status_code=404, detail="User not found.")
        exists = (await db.execute(select(UserBlocks.id).where(
            UserBlocks.blocker_id == user_id, UserBlocks.blocked_id == other_id
        ))).first()
        if not exists:
            db.add(UserBlocks(blocker_id=user_id, blocked_id=other_id, created_at=datetime.utcnow()))
            await db.commit()
        return {"success": "User blocked. They can no longer message you or make offers to you."}

    async def unblock(self, user_id: int, other_id: int, db: AsyncSession) -> dict:
        await db.execute(delete(UserBlocks).where(UserBlocks.blocker_id == user_id, UserBlocks.blocked_id == other_id))
        await db.commit()
        return {"success": "User unblocked."}

    async def report(self, user_id: int, payload, db: AsyncSession) -> dict:
        if payload.target_type == "message":
            m = (await db.execute(select(Messages).where(Messages.id == payload.target_id))).scalar_one_or_none()
            if not m or user_id not in (m.sender, m.receiver):
                raise HTTPException(status_code=404, detail="Message not found.")
        duplicate = (await db.execute(select(Reports.id).where(
            Reports.reporter_id == user_id, Reports.target_type == payload.target_type,
            Reports.target_id == payload.target_id, Reports.status == "open",
        ))).first()
        if duplicate:
            return {"success": "You already reported this. Our team will review it."}
        db.add(Reports(reporter_id=user_id, target_type=payload.target_type, target_id=payload.target_id,
                       reason=payload.reason, details=payload.details, status="open", created_at=datetime.utcnow()))
        await db.commit()
        return {"success": "Report submitted. Our team will review it."}
