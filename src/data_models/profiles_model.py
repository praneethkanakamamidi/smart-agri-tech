from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Numeric, Text, JSON, Index
from src.db_connections.postgresql_conn import Base


class FarmerProfiles(Base):
    """Farmer-specific onboarding details. Bank/UPI details are stored encrypted."""
    __tablename__ = "farmer_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False)
    farm_name = Column(String(120))
    farm_address = Column(String(255))
    village = Column(String(80))
    pincode = Column(String(10))
    state = Column(Integer, ForeignKey('states.id', ondelete='SET NULL'), nullable=True)
    district = Column(Integer, ForeignKey('districts.id', ondelete='SET NULL'), nullable=True)
    produce_categories = Column(JSON, nullable=True)  # list of category ids
    farming_type = Column(String(40))  # conventional | organic | natural | mixed
    farm_size_acres = Column(Numeric(10, 2), nullable=True)
    harvest_schedule = Column(Text, nullable=True)
    payout_method = Column(String(20))  # bank | upi
    bank_account_holder = Column(String(120))
    bank_account_number_enc = Column(String(512))
    bank_ifsc = Column(String(15))
    upi_id_enc = Column(String(512))
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class VendorProfiles(Base):
    """Vendor / business onboarding details."""
    __tablename__ = "vendor_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False)
    business_name = Column(String(120))
    business_type = Column(String(30))  # retailer | wholesaler | restaurant | trader | processor
    business_address = Column(String(255))
    pincode = Column(String(10))
    state = Column(Integer, ForeignKey('states.id', ondelete='SET NULL'), nullable=True)
    district = Column(Integer, ForeignKey('districts.id', ondelete='SET NULL'), nullable=True)
    gstin = Column(String(20))
    purchase_categories = Column(JSON, nullable=True)
    typical_quantity = Column(Numeric(12, 2), nullable=True)
    typical_quantity_unit = Column(String(20))
    billing_address = Column(String(255))
    delivery_preference = Column(String(30))
    payment_preference = Column(String(30))
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class VerificationRequests(Base):
    """Identity / farm / business verification submitted by a user and reviewed by an admin."""
    __tablename__ = "verification_requests"
    __table_args__ = (
        Index("idx_verification_requests_user", "user_id", "status"),
        Index("idx_verification_requests_status", "status", "submitted_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    verification_type = Column(String(20), nullable=False)  # identity | farm | business
    document_type = Column(String(40), nullable=False)
    document_number_masked = Column(String(40))
    file_ids = Column(JSON, nullable=True)
    status = Column(String(30), nullable=False)  # PENDING_VERIFICATION | VERIFIED | REJECTED
    reviewer_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    review_notes = Column(String(500))
    submitted_at = Column(DateTime)
    reviewed_at = Column(DateTime)
