from sqlalchemy import (
    Column, String, Integer, DateTime, Date, ForeignKey, Numeric, Boolean, UniqueConstraint, Text, Index, text,
)
from sqlalchemy.orm import relationship
from src.db_connections.postgresql_conn import Base

# Offer states
DRAFT = "DRAFT"
PENDING = "PENDING"
COUNTERED = "COUNTERED"
ACCEPTED = "ACCEPTED"
REJECTED = "REJECTED"
WITHDRAWN = "WITHDRAWN"
EXPIRED = "EXPIRED"
CANCELLED = "CANCELLED"

# Negotiation states
NEG_OPEN = "OPEN"


class Negotiations(Base):
    """A bargaining session between one vendor and one farmer over one listing."""
    __tablename__ = "negotiations"
    __table_args__ = (
        Index("idx_negotiations_vendor_updated", "vendor", "updated_at"),
        Index("idx_negotiations_farmer_updated", "farmer", "updated_at"),
        Index("idx_negotiations_listing", "listing_id", "vendor", "status"),
        Index("idx_negotiations_order", "order_id", postgresql_where=text("order_id IS NOT NULL")),
        Index("idx_negotiations_created", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    listing_id = Column(Integer, ForeignKey('farmer_inventory.id', ondelete='CASCADE'), nullable=False)
    vendor = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    farmer = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    status = Column(String(20), nullable=False)  # OPEN | ACCEPTED | REJECTED | EXPIRED | CANCELLED
    current_offer_id = Column(Integer, nullable=True)  # the latest offer (actionable only if PENDING)
    order_id = Column(Integer, ForeignKey('orders.id', ondelete='SET NULL'), nullable=True)
    source = Column(String(30), default="listing")  # listing | buy_request | reorder
    source_ref_id = Column(Integer, nullable=True)
    cancel_reason = Column(String(255))
    cancelled_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    closed_at = Column(DateTime)

    listing_rel = relationship("FarmerInventory", foreign_keys=[listing_id], lazy="raise")
    vendor_user = relationship("Users", foreign_keys=[vendor], lazy="raise")
    farmer_user = relationship("Users", foreign_keys=[farmer], lazy="raise")


class Offers(Base):
    """
    One immutable proposal in a negotiation. A counteroffer creates a new version that
    supersedes the previous one; earlier versions are never overwritten.
    """
    __tablename__ = "offers"
    __table_args__ = (
        UniqueConstraint('negotiation_id', 'version', name='uq_offer_version'),
        Index("idx_offers_pending_expiry", "expires_at", postgresql_where=text("status = 'PENDING'")),
        Index("idx_offers_recipient", "recipient"),
        Index("idx_offers_offered_by", "offered_by"),
        Index("idx_offers_supersedes", "supersedes_offer_id", postgresql_where=text("supersedes_offer_id IS NOT NULL")),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    negotiation_id = Column(Integer, ForeignKey('negotiations.id', ondelete='CASCADE'), nullable=False)
    version = Column(Integer, nullable=False)
    offered_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    recipient = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    offered_by_role = Column(String(10), nullable=False)  # farmer | vendor
    quantity = Column(Numeric(12, 2), nullable=False)
    unit = Column(String(20), nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False)
    subtotal = Column(Numeric(14, 2), nullable=False)
    delivery_preference = Column(String(30))  # pickup | farmer_delivery | vendor_transport | third_party
    preferred_date = Column(Date)
    packaging = Column(String(30))
    quality_spec = Column(String(255))
    message = Column(Text)
    status = Column(String(20), nullable=False)
    supersedes_offer_id = Column(Integer, ForeignKey('offers.id', ondelete='SET NULL'), nullable=True)
    expires_at = Column(DateTime)
    expiry_notified = Column(Boolean, default=False, nullable=False)
    responded_at = Column(DateTime)
    created_at = Column(DateTime)
