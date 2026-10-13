from sqlalchemy import Column, String, Integer, DateTime, Date, ForeignKey, Numeric, UniqueConstraint, Index, text
from src.db_connections.postgresql_conn import Base


class ListingImages(Base):
    __tablename__ = "listing_images"
    __table_args__ = (
        Index("idx_listing_images_listing", "listing_id", "sort_order"),
        Index("idx_listing_images_file", "file_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    listing_id = Column(Integer, ForeignKey('farmer_inventory.id', ondelete='CASCADE'), nullable=False)
    file_id = Column(String(36), ForeignKey('stored_files.id', ondelete='CASCADE'), nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime)


class ListingPriceTiers(Base):
    """Farmer-proposed quantity discounts: price_per_unit applies from min_quantity upwards."""
    __tablename__ = "listing_price_tiers"
    __table_args__ = (UniqueConstraint('listing_id', 'min_quantity', name='uq_listing_price_tier'),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    listing_id = Column(Integer, ForeignKey('farmer_inventory.id', ondelete='CASCADE'), nullable=False)
    min_quantity = Column(Numeric(12, 2), nullable=False)
    price_per_unit = Column(Numeric(12, 2), nullable=False)


class ListingCertifications(Base):
    """Optional certificate (organic, lab test, inspection). Shown as verified only after admin review."""
    __tablename__ = "listing_certifications"
    __table_args__ = (
        Index("idx_listing_certifications_listing", "listing_id"),
        Index("idx_listing_certifications_status", "status", "created_at"),
        Index("idx_listing_certifications_file", "file_id", postgresql_where=text("file_id IS NOT NULL")),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    listing_id = Column(Integer, ForeignKey('farmer_inventory.id', ondelete='CASCADE'), nullable=False)
    cert_type = Column(String(40), nullable=False)  # organic | lab_test | inspection | other
    issuer = Column(String(120))
    file_id = Column(String(36), ForeignKey('stored_files.id', ondelete='SET NULL'), nullable=True)
    valid_until = Column(Date, nullable=True)
    status = Column(String(20), nullable=False)  # pending | verified | rejected
    reviewed_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    review_notes = Column(String(255))
    created_at = Column(DateTime)
    reviewed_at = Column(DateTime)


class SavedListings(Base):
    """Vendor wishlist of listings; saved_price lets us notify on price changes."""
    __tablename__ = "saved_listings"
    __table_args__ = (
        UniqueConstraint('user_id', 'listing_id', name='uq_saved_listing'),
        Index("idx_saved_listings_listing", "listing_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    listing_id = Column(Integer, ForeignKey('farmer_inventory.id', ondelete='CASCADE'), nullable=False)
    saved_price = Column(Numeric(12, 2))
    created_at = Column(DateTime)


class InventoryReservations(Base):
    """Stock held for an order. Released on cancellation/expiry, consumed on delivery."""
    __tablename__ = "inventory_reservations"
    __table_args__ = (
        Index("idx_inventory_reservations_order", "order_id", "status"),
        Index("idx_inventory_reservations_listing", "listing_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    listing_id = Column(Integer, ForeignKey('farmer_inventory.id', ondelete='CASCADE'), nullable=False)
    order_id = Column(Integer, ForeignKey('orders.id', ondelete='CASCADE'), nullable=False)
    quantity = Column(Numeric(12, 2), nullable=False)
    status = Column(String(20), nullable=False)  # active | consumed | released | expired
    expires_at = Column(DateTime, nullable=True)  # null = held until fulfilment
    reason = Column(String(120))
    created_at = Column(DateTime)
    released_at = Column(DateTime)


class InventoryMovements(Base):
    """Append-only stock ledger for a listing."""
    __tablename__ = "inventory_movements"
    __table_args__ = (Index("idx_inventory_movements_listing", "listing_id", "created_at"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    listing_id = Column(Integer, ForeignKey('farmer_inventory.id', ondelete='CASCADE'), nullable=False)
    movement_type = Column(String(20), nullable=False)  # add | adjust | reserve | release | sell
    quantity = Column(Numeric(12, 2), nullable=False)
    available_after = Column(Numeric(12, 2), nullable=False)
    reserved_after = Column(Numeric(12, 2), nullable=False)
    sold_after = Column(Numeric(12, 2), nullable=False)
    ref_type = Column(String(30))
    ref_id = Column(Integer)
    actor_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    note = Column(String(255))
    created_at = Column(DateTime)


class HarvestPlans(Base):
    """Farmer's upcoming harvest; can be published as a pre-harvest listing."""
    __tablename__ = "harvest_plans"
    __table_args__ = (
        Index("idx_harvest_plans_farmer_date", "farmer", "expected_harvest_date"),
        Index("idx_harvest_plans_listing", "listing_id", postgresql_where=text("listing_id IS NOT NULL")),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    farmer = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    crop = Column(Integer, ForeignKey('crops.id', ondelete='CASCADE'), nullable=False)
    variety = Column(String(60))
    expected_quantity = Column(Numeric(12, 2), nullable=False)
    unit = Column(String(20), default="kg", nullable=False)
    expected_harvest_date = Column(Date, nullable=False)
    area_acres = Column(Numeric(10, 2))
    notes = Column(String(500))
    status = Column(String(20), nullable=False)  # planned | harvested | cancelled
    listing_id = Column(Integer, ForeignKey('farmer_inventory.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
