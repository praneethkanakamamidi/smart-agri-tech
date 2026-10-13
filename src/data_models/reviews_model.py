from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, UniqueConstraint, CheckConstraint, Boolean, Index
from sqlalchemy.orm import relationship
from src.db_connections.postgresql_conn import Base


class Reviews(Base):
    """Rating left by one party of an order for the other (farmer <-> vendor)."""
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint('order_id', 'reviewer', name='uq_reviews_order_reviewer'),
        CheckConstraint('rating BETWEEN 1 AND 5', name='ck_reviews_rating'),
        Index('idx_reviews_reviewee', 'reviewee'),
        Index('idx_reviews_reviewer', 'reviewer'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('orders.id', ondelete='CASCADE'), nullable=False)
    reviewer = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    reviewee = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    rating = Column(Integer, nullable=False)  # overall
    quality_rating = Column(Integer)  # produce quality (vendor -> farmer)
    communication_rating = Column(Integer)
    reliability_rating = Column(Integer)  # fulfilment / payment reliability
    quantity_accuracy_rating = Column(Integer)  # vendor -> farmer
    comment = Column(String(500), nullable=True)
    response = Column(String(500))  # reviewee's public reply
    response_at = Column(DateTime)
    is_hidden = Column(Boolean, default=False, nullable=False)
    hidden_reason = Column(String(255))
    moderated_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime)

    reviewer_user = relationship("Users", foreign_keys=[reviewer], lazy="raise")
