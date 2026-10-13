from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Boolean, JSON, Index
from sqlalchemy.orm import relationship
from src.db_connections.postgresql_conn import Base

# Dispute states
OPEN = "open"
UNDER_REVIEW = "under_review"
AWAITING_EVIDENCE = "awaiting_evidence"
RESOLVED = "resolved"
REJECTED = "rejected"
WITHDRAWN = "withdrawn"
ACTIVE_DISPUTE_STATES = (OPEN, UNDER_REVIEW, AWAITING_EVIDENCE)

DISPUTE_REASONS = (
    "quality_issue", "quantity_mismatch", "incorrect_product", "late_delivery", "not_delivered",
    "damaged_produce", "payment_issue", "refund_disagreement", "misrepresentation", "unresolved_cancellation",
    "other",
)


class Disputes(Base):
    """A complaint raised on an order by the farmer or vendor, resolved by an admin."""
    __tablename__ = "disputes"
    __table_args__ = (Index("idx_disputes_status", "status"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('orders.id', ondelete='CASCADE'), nullable=False)
    raised_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    against = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    reason = Column(String(40), nullable=False)
    description = Column(String(1000), nullable=True)
    status = Column(String(20), nullable=False)
    resolution = Column(String(1000), nullable=True)
    resolution_type = Column(String(30))  # full_refund | partial_refund | replacement | no_action
    refund_amount = Column(String(20))
    resolved_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    assigned_to = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    escalated = Column(Boolean, default=False, nullable=False)
    escalated_at = Column(DateTime)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    resolved_at = Column(DateTime, nullable=True)

    raised_by_user = relationship("Users", foreign_keys=[raised_by], lazy="raise")
    against_user = relationship("Users", foreign_keys=[against], lazy="raise")


class DisputeMessages(Base):
    """Case history: responses and evidence from either party or an admin."""
    __tablename__ = "dispute_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dispute_id = Column(Integer, ForeignKey('disputes.id', ondelete='CASCADE'), nullable=False)
    author_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    body = Column(String(2000), nullable=False)
    file_ids = Column(JSON)
    kind = Column(String(20), default="message", nullable=False)  # message | evidence | status_change | internal_note
    created_at = Column(DateTime)
