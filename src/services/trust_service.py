"""Objective trust indicators shown on public profiles and listings."""
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.platform_settings import get_setting
from src.data_models.disputes_model import Disputes, WITHDRAWN, REJECTED
from src.data_models.miscellaneous_model import Miscellaneous_Data
from src.data_models.orders_model import Orders, PENDING_CONFIRMATION, COMPLETED, DELIVERED
from src.data_models.profiles_model import VerificationRequests
from src.data_models.reviews_model import Reviews
from src.data_models.users_model import Users, VERIFIED


def _rate(numerator: int, denominator: int, min_sample: int):
    if denominator < min_sample or denominator == 0:
        return None
    return round(numerator * 100.0 / denominator, 1)


async def trust_indicators(db: AsyncSession, user_id: int) -> dict:
    min_sample = int(await get_setting(db, "min_sample_size"))
    party = or_(Orders.farmer == user_id, Orders.vendor == user_id)
    status_rows = dict((await db.execute(
        select(Miscellaneous_Data.value, func.count(Orders.id))
        .join(Miscellaneous_Data, Orders.status == Miscellaneous_Data.id)
        .where(party)
        .group_by(Miscellaneous_Data.value)
    )).all())
    agreed_orders = sum(count for value, count in status_rows.items() if value != PENDING_CONFIRMATION)
    completed = status_rows.get(COMPLETED, 0) + status_rows.get(DELIVERED, 0)

    cancelled_by_user = (await db.execute(
        select(func.count(Orders.id)).where(party, Orders.cancelled_by == user_id)
    )).scalar() or 0

    with_deadline = (await db.execute(
        select(
            func.count(Orders.id),
            func.count(Orders.id).filter(func.date(Orders.delivered_at) <= Orders.expected_delivery_date),
        ).where(Orders.farmer == user_id, Orders.delivered_at.is_not(None), Orders.expected_delivery_date.is_not(None))
    )).one()

    disputes_against = (await db.execute(
        select(func.count(Disputes.id)).where(Disputes.against == user_id, Disputes.status.not_in((WITHDRAWN, REJECTED)))
    )).scalar() or 0

    avg_rating, review_count = (await db.execute(
        select(func.avg(Reviews.rating), func.count(Reviews.id))
        .where(Reviews.reviewee == user_id, Reviews.is_hidden.is_(False))
    )).one()

    user = (await db.execute(select(Users).where(Users.id == user_id))).scalar_one()
    verified_types = set((await db.execute(
        select(VerificationRequests.verification_type).where(
            VerificationRequests.user_id == user_id, VerificationRequests.status == VERIFIED
        )
    )).scalars().all())
    badges = []
    if "identity" in verified_types:
        badges.append("verified_identity")
    if "farm" in verified_types:
        badges.append("verified_farm")
    if "business" in verified_types:
        badges.append("verified_business")
    if user.phone_verified:
        badges.append("verified_phone")

    return {
        "verification_status": user.verification_status,
        "badges": badges,
        "completed_orders": completed,
        "total_agreed_orders": agreed_orders,
        "cancellation_rate_percent": _rate(cancelled_by_user, agreed_orders, min_sample),
        "on_time_fulfilment_percent": _rate(with_deadline[1], with_deadline[0], min_sample),
        "dispute_rate_percent": _rate(disputes_against, agreed_orders, min_sample),
        "average_rating": round(float(avg_rating), 2) if avg_rating is not None and review_count >= 1 else None,
        "review_count": review_count,
        "rating_is_reliable": review_count >= min_sample,
        "min_sample_size": min_sample,
        "note": "Rates are shown only once there are at least min_sample_size data points.",
    }


async def ratings_for(db: AsyncSession, user_ids) -> dict[int, tuple[float, int]]:
    user_ids = list({u for u in user_ids if u})
    if not user_ids:
        return {}
    rows = (await db.execute(
        select(Reviews.reviewee, func.avg(Reviews.rating), func.count(Reviews.id))
        .where(Reviews.reviewee.in_(user_ids), Reviews.is_hidden.is_(False))
        .group_by(Reviews.reviewee)
    )).all()
    return {row[0]: (round(float(row[1]), 2), row[2]) for row in rows}


async def completed_counts(db: AsyncSession, user_ids) -> dict[int, int]:
    user_ids = list({u for u in user_ids if u})
    if not user_ids:
        return {}
    rows = (await db.execute(
        select(Orders.farmer, func.count(Orders.id))
        .join(Miscellaneous_Data, Orders.status == Miscellaneous_Data.id)
        .where(Orders.farmer.in_(user_ids), Miscellaneous_Data.value.in_((COMPLETED, DELIVERED)))
        .group_by(Orders.farmer)
    )).all()
    return dict(rows)
