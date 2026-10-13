from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import audit
from src.data_models.miscellaneous_model import Miscellaneous_Data
from src.data_models.orders_model import Orders, DELIVERED, COMPLETED
from src.data_models.reviews_model import Reviews
from src.data_models.users_model import Users
from src.helpers.serializers import model_to_dict
from src.services.notifications_service import notify_user
from src.services.trust_service import trust_indicators

REVIEWABLE_ORDER_STATUSES = (DELIVERED, COMPLETED)


class ReviewsService:
    async def create_review(self, payload, reviewer_id: int, db: AsyncSession):
        stmt = select(Orders).where(Orders.id == payload.order_id).options(joinedload(Orders.status_rel))
        order = (await db.execute(stmt)).scalar_one_or_none()
        if not order or reviewer_id not in (order.farmer, order.vendor):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")
        order_status = order.status_rel.value if order.status_rel else None
        if order_status not in REVIEWABLE_ORDER_STATUSES:
            raise HTTPException(status_code=400, detail="You can review only after the order is delivered.")
        if (await db.execute(select(Reviews.id).where(
            Reviews.order_id == order.id, Reviews.reviewer == reviewer_id
        ))).scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You have already reviewed this order.")

        reviewing_farmer = reviewer_id == order.vendor
        if not reviewing_farmer and (payload.quality_rating or payload.quantity_accuracy_rating):
            raise HTTPException(status_code=422, detail="Quality and quantity ratings apply to farmers only.")
        reviewee_id = order.farmer if reviewing_farmer else order.vendor
        review = Reviews(
            order_id=order.id, reviewer=reviewer_id, reviewee=reviewee_id, rating=payload.rating,
            quality_rating=payload.quality_rating, communication_rating=payload.communication_rating,
            reliability_rating=payload.reliability_rating, quantity_accuracy_rating=payload.quantity_accuracy_rating,
            comment=payload.comment, is_hidden=False, created_at=datetime.utcnow(),
        )
        db.add(review)
        await db.flush()
        await notify_user(db, reviewee_id, "review_received", {"rating": payload.rating}, ref_type="review", ref_id=review.id)
        await db.commit()
        return {"success": "Review submitted.", "review_id": review.id}

    async def respond(self, review_id: int, user_id: int, text: str, db: AsyncSession) -> dict:
        review = (await db.execute(select(Reviews).where(Reviews.id == review_id))).scalar_one_or_none()
        if not review or review.reviewee != user_id:
            raise HTTPException(status_code=404, detail="Review not found.")
        if review.response:
            raise HTTPException(status_code=409, detail="You already replied to this review.")
        review.response = text
        review.response_at = datetime.utcnow()
        user = (await db.execute(select(Users).where(Users.id == user_id))).scalar_one()
        await notify_user(db, review.reviewer, "review_response", {"party": f"{user.first_name} {user.last_name}".strip()},
                          ref_type="review", ref_id=review.id)
        await db.commit()
        return {"success": "Reply posted."}

    async def moderate(self, review_id: int, admin_id: int, hidden: bool, reason: str, db: AsyncSession) -> dict:
        review = (await db.execute(select(Reviews).where(Reviews.id == review_id))).scalar_one_or_none()
        if not review:
            raise HTTPException(status_code=404, detail="Review not found.")
        before = {"is_hidden": review.is_hidden}
        review.is_hidden = hidden
        review.hidden_reason = reason if hidden else None
        review.moderated_by = admin_id
        audit(db, "review.moderated", "review", review.id, actor_id=admin_id, actor_role="admin", before=before,
              after={"is_hidden": hidden, "reason": reason})
        await db.commit()
        return {"success": "Review hidden." if hidden else "Review restored."}

    async def get_rating_summary(self, user_id: int, db: AsyncSession) -> dict:
        visible = (Reviews.reviewee == user_id, Reviews.is_hidden.is_(False))
        avg_rating, total, quality, communication, reliability, quantity = (await db.execute(
            select(func.avg(Reviews.rating), func.count(Reviews.id), func.avg(Reviews.quality_rating),
                   func.avg(Reviews.communication_rating), func.avg(Reviews.reliability_rating),
                   func.avg(Reviews.quantity_accuracy_rating)).where(*visible)
        )).one()
        distribution = {star: 0 for star in range(5, 0, -1)}
        distribution.update(dict((await db.execute(
            select(Reviews.rating, func.count(Reviews.id)).where(*visible).group_by(Reviews.rating)
        )).all()))
        r = lambda v: round(float(v), 2) if v is not None else None  # noqa: E731
        trust = await trust_indicators(db, user_id)
        return {
            "user_id": user_id,
            "average_rating": r(avg_rating),
            "total_reviews": total,
            "is_reliable": trust["rating_is_reliable"],
            "dimensions": {"quality": r(quality), "communication": r(communication),
                           "reliability": r(reliability), "quantity_accuracy": r(quantity)},
            "distribution": distribution,
            "completed_orders": trust["completed_orders"],
        }

    async def get_user_reviews(self, user_id: int, db: AsyncSession, page: int = 1, page_size: int = 10):
        summary = await self.get_rating_summary(user_id, db)
        reviews = (await db.execute(
            select(Reviews).where(Reviews.reviewee == user_id, Reviews.is_hidden.is_(False))
            .order_by(Reviews.created_at.desc()).options(joinedload(Reviews.reviewer_user))
            .limit(page_size).offset((page - 1) * page_size)
        )).scalars().all()
        summary.update({
            "page": page, "page_size": page_size,
            "data": [
                model_to_dict(r, reviewer_name=(f"{r.reviewer_user.first_name} {r.reviewer_user.last_name}".strip()
                                                if r.reviewer_user else None))
                for r in reviews
            ],
        })
        return summary

    async def get_pending_reviews(self, user_id: int, db: AsyncSession):
        reviewed = select(Reviews.order_id).where(Reviews.reviewer == user_id)
        orders = (await db.execute(
            select(Orders).join(Miscellaneous_Data, Orders.status == Miscellaneous_Data.id)
            .where((Orders.farmer == user_id) | (Orders.vendor == user_id),
                   Miscellaneous_Data.value.in_(REVIEWABLE_ORDER_STATUSES), Orders.id.not_in(reviewed))
            .order_by(Orders.updated_at.desc().nullslast())
        )).scalars().all()
        return [
            {"order_id": o.id, "order_number": o.order_number,
             "review_for_user_id": o.vendor if o.farmer == user_id else o.farmer,
             "crop_name": (o.terms_snapshot or {}).get("produce", {}).get("display_name")}
            for o in orders
        ]
