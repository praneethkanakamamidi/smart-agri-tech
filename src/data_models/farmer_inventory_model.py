from sqlalchemy import Column, String, Integer, DateTime, Date, ForeignKey, Numeric, Boolean, Index, text
from sqlalchemy.orm import relationship
from src.db_connections.postgresql_conn import Base

# Listing status values
DRAFT = "draft"
ACTIVE = "active"
PAUSED = "paused"
RESERVED = "reserved"  # all remaining stock is reserved by accepted deals
SOLD = "sold"
EXPIRED = "expired"
REMOVED = "removed"  # taken down by moderation
ARCHIVED = "archived"  # deleted by the farmer but kept because orders reference it

# Columns that must never be shown to anyone but the listing's farmer. Exact pickup coordinates
# are private too: buyers see the computed distance, not the location.
PRIVATE_LISTING_FIELDS = {"min_acceptable_price", "low_stock_threshold", "pickup_latitude", "pickup_longitude"}


class FarmerInventory(Base):
    """
    A produce listing. Quantities are in the listing's `unit`:
    weight_kg = available (unreserved) quantity, reserved_qty = held for accepted deals,
    sold_qty = fulfilled. (`weight_kg` keeps its historical name for API compatibility.)
    """
    __tablename__ = "farmer_inventory"
    __table_args__ = (
        Index("idx_listing_farmer", "created_by"),
        Index("idx_listing_market", "status", "crop", postgresql_where=text("deleted_at IS NULL")),
        Index("idx_listing_crop", "crop"),
        # Default marketplace feed: active listings, newest first.
        Index("idx_listing_feed_recent", text("created_at DESC NULLS LAST"), text("id DESC"),
              postgresql_where=text("status = 'active' AND deleted_at IS NULL")),
        Index("idx_listing_available_until", "available_until", postgresql_where=text("available_until IS NOT NULL")),
        Index("idx_listing_soil", "soil", postgresql_where=text("soil IS NOT NULL")),
        Index("idx_listing_fertilizer", "fertilizer", postgresql_where=text("fertilizer IS NOT NULL")),
    )

    id = Column(Integer, primary_key=True)
    crop = Column(Integer, ForeignKey('crops.id', ondelete='CASCADE'))
    fertilizer = Column(Integer, ForeignKey('fertilizers.id', ondelete='SET NULL'))
    soil = Column(Integer, ForeignKey('soil.id', ondelete='SET NULL'))
    weight_kg = Column(Numeric(12, 2))  # available quantity
    proposed_cost = Column(Numeric(12, 2))  # asking price per unit
    description = Column(String(500))
    created_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    updated_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    quality_grade = Column(String(10), nullable=True)
    harvest_date = Column(Date, nullable=True)  # future date = pre-harvest listing
    available_until = Column(Date, nullable=True)  # listing expiry / freshness limit
    variety = Column(String(60), nullable=True)
    unit = Column(String(20), default="kg", nullable=False)
    min_order_qty = Column(Numeric(12, 2), nullable=True)
    min_acceptable_price = Column(Numeric(12, 2), nullable=True)  # PRIVATE bargaining floor
    packaging = Column(String(30), nullable=True)  # loose | bags | crates | other
    availability_date = Column(Date, nullable=True)  # when the produce can be supplied
    status = Column(String(20), default=ACTIVE, nullable=False)
    reserved_qty = Column(Numeric(12, 2), default=0, nullable=False)
    sold_qty = Column(Numeric(12, 2), default=0, nullable=False)
    batch_code = Column(String(40), nullable=True)
    organic_claim = Column(Boolean, default=False, nullable=False)
    organic_verified = Column(Boolean, default=False, nullable=False)
    delivery_options = Column(String(100), nullable=True)  # csv: pickup,farmer_delivery,vendor_transport,third_party
    views_count = Column(Integer, default=0, nullable=False)
    inquiries_count = Column(Integer, default=0, nullable=False)
    low_stock_threshold = Column(Numeric(12, 2), nullable=True)
    moderation_reason = Column(String(255), nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    # Optional pickup point when the produce isn't at the farm location on the farmer's profile.
    pickup_latitude = Column(Numeric(9, 6), nullable=True)
    pickup_longitude = Column(Numeric(9, 6), nullable=True)

    crop_rel = relationship("Crops", foreign_keys=[crop], lazy="raise")
    soil_rel = relationship("Soil", foreign_keys=[soil], lazy="raise")
    fertilizer_rel = relationship("Fertilizers", foreign_keys=[fertilizer], lazy="raise")
    created_by_user = relationship("Users", foreign_keys=[created_by], lazy="raise")
