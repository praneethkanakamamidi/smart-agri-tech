from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Boolean, Index
from sqlalchemy.orm import relationship
from src.db_connections.postgresql_conn import Base


class Messages(Base):
    """
    Direct messages between two users. A message can reference the listing, negotiation,
    order or dispute it is about, so separate deals don't get mixed up.
    """
    __tablename__ = "messages"
    __table_args__ = (
        Index("idx_messages_sender", "sender"),
        Index("idx_messages_receiver_read", "receiver", "is_read"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    sender = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    receiver = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    offer_id = Column(Integer, ForeignKey('market_offers.id', ondelete='SET NULL'), nullable=True)  # legacy
    order_id = Column(Integer, ForeignKey('orders.id', ondelete='SET NULL'), nullable=True)
    listing_id = Column(Integer, ForeignKey('farmer_inventory.id', ondelete='SET NULL'), nullable=True)
    negotiation_id = Column(Integer, ForeignKey('negotiations.id', ondelete='SET NULL'), nullable=True)
    dispute_id = Column(Integer, ForeignKey('disputes.id', ondelete='SET NULL'), nullable=True)
    attachment_file_id = Column(String(36), ForeignKey('stored_files.id', ondelete='SET NULL'), nullable=True)
    message_type = Column(String(20), default="text", nullable=False)  # text | image | offer_summary | system
    body = Column(String(1000), nullable=False)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime)

    sender_user = relationship("Users", foreign_keys=[sender], lazy="raise")
    receiver_user = relationship("Users", foreign_keys=[receiver], lazy="raise")
