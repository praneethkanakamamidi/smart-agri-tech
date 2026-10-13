from sqlalchemy import Column, String, Integer, DateTime, Date, ForeignKey, Float, Boolean, UniqueConstraint, Index, text
from sqlalchemy.orm import relationship
from src.db_connections.postgresql_conn import Base


class BuyRequests(Base):
    """
    A vendor's procurement request ("I need 1000 kg rice by the 20th").
    Farmers quote from their listings; the vendor compares, negotiates and accepts (possibly several).
    """
    __tablename__ = "buy_requests"
    __table_args__ = (
        Index("idx_buy_requests_status_crop", "status", "crop"),
        Index("idx_buy_requests_vendor", "vendor"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    vendor = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    crop = Column(Integer, ForeignKey('crops.id', ondelete='CASCADE'), nullable=False)
    quantity_kg = Column(Float, nullable=False)  # requested quantity in `unit`
    unit = Column(String(20), default="kg")
    max_price_per_kg = Column(Float, nullable=True)
    quality_grade = Column(String(10))
    quality_spec = Column(String(255))
    packaging = Column(String(30))
    state = Column(Integer, ForeignKey('states.id', ondelete='SET NULL'), nullable=True)
    district = Column(Integer, ForeignKey('districts.id', ondelete='SET NULL'), nullable=True)
    needed_by = Column(Date, nullable=True)
    description = Column(String(255), nullable=True)
    status = Column(String(20), nullable=False)  # open | closed | fulfilled
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    vendor_user = relationship("Users", foreign_keys=[vendor], lazy="raise")
    crop_rel = relationship("Crops", foreign_keys=[crop], lazy="raise")
    state_rel = relationship("States", foreign_keys=[state], lazy="raise")
    district_rel = relationship("Districts", foreign_keys=[district], lazy="raise")


class BuyRequestInvites(Base):
    """Vendor invited a specific farmer to quote."""
    __tablename__ = "buy_request_invites"
    __table_args__ = (
        UniqueConstraint('buy_request_id', 'farmer', name='uq_buy_request_invite'),
        Index("idx_buy_request_invites_farmer", "farmer"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    buy_request_id = Column(Integer, ForeignKey('buy_requests.id', ondelete='CASCADE'), nullable=False)
    farmer = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    created_at = Column(DateTime)


class BuyRequestResponses(Base):
    """A farmer's quotation to fulfil (part of) a buy request from one of their listings."""
    __tablename__ = "buy_request_responses"
    __table_args__ = (
        Index("idx_buy_request_responses_request", "buy_request_id"),
        Index("idx_buy_request_responses_farmer", "farmer"),
        Index("idx_buy_request_responses_listing", "farmer_inventory"),
        Index("idx_buy_request_responses_negotiation", "negotiation_id",
              postgresql_where=text("negotiation_id IS NOT NULL")),
        Index("idx_buy_request_responses_order", "order_id", postgresql_where=text("order_id IS NOT NULL")),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    buy_request_id = Column(Integer, ForeignKey('buy_requests.id', ondelete='CASCADE'), nullable=False)
    farmer = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    farmer_inventory = Column(Integer, ForeignKey('farmer_inventory.id', ondelete='CASCADE'), nullable=False)
    price_per_kg = Column(Float, nullable=False)
    quantity_kg = Column(Float, nullable=False)
    message = Column(String(255), nullable=True)
    status = Column(String(20), nullable=False)  # pending | accepted | rejected | withdrawn | negotiating
    shortlisted = Column(Boolean, default=False, nullable=False)
    negotiation_id = Column(Integer, ForeignKey('negotiations.id', ondelete='SET NULL'), nullable=True)
    order_id = Column(Integer, ForeignKey('orders.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    buy_request_rel = relationship("BuyRequests", foreign_keys=[buy_request_id], lazy="raise")
    farmer_user = relationship("Users", foreign_keys=[farmer], lazy="raise")
    farmer_inventory_rel = relationship("FarmerInventory", foreign_keys=[farmer_inventory], lazy="raise")
