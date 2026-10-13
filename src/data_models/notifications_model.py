from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Boolean, Index, text
from src.db_connections.postgresql_conn import Base

# Notification categories drive channel and quiet-hour policy.
SECURITY = "security"  # always delivered immediately
TRANSACTIONAL = "transactional"  # offers, orders, payments
REMINDER = "reminder"  # expiring soon, payment reminders (respects quiet hours)
PROMOTIONAL = "promotional"  # only with opt-in, respects quiet hours


class Notifications(Base):
    """In-app notifications (new offer, order update, message, review, ...)."""
    __tablename__ = "notifications"
    __table_args__ = (
        Index("idx_notifications_user_read", "user_id", "is_read"),
        Index("uq_notifications_dedupe", "user_id", "dedupe_key", unique=True,
              postgresql_where=text("dedupe_key IS NOT NULL")),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    type = Column(String(40), nullable=False)  # e.g. offer_received, order_status, new_message
    title = Column(String(120), nullable=False)
    message = Column(String(500))
    ref_type = Column(String(40), nullable=True)  # offer | negotiation | order | buy_request | message | review | dispute | inventory
    ref_id = Column(Integer, nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)
    category = Column(String(20), default=TRANSACTIONAL, nullable=False)
    dedupe_key = Column(String(120), nullable=True)  # unique per user when set
    created_at = Column(DateTime)
