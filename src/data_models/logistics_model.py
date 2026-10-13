from sqlalchemy import Column, String, Integer, DateTime, Date, ForeignKey, Numeric, Boolean, Text
from src.db_connections.postgresql_conn import Base


class Shipments(Base):
    """Pickup / delivery arrangement and proof for one order."""
    __tablename__ = "shipments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('orders.id', ondelete='CASCADE'), unique=True, nullable=False)
    mode = Column(String(30), nullable=False)
    status = Column(String(20), nullable=False)  # planned | picked_up | in_transit | delivered | failed
    pickup_date = Column(Date)
    window_start = Column(DateTime)
    window_end = Column(DateTime)
    pickup_address = Column(String(255))
    pickup_instructions = Column(Text)
    delivery_address = Column(String(255))
    delivery_contact_name = Column(String(80))
    delivery_contact_phone = Column(String(20))
    transporter_name = Column(String(120))
    vehicle_number = Column(String(30))
    dispatched_at = Column(DateTime)
    pickup_proof_file_id = Column(String(36), ForeignKey('stored_files.id', ondelete='SET NULL'), nullable=True)
    delivery_otp_hash = Column(String(128))
    delivery_otp_expires_at = Column(DateTime)
    delivered_at = Column(DateTime)
    delivery_proof_file_id = Column(String(36), ForeignKey('stored_files.id', ondelete='SET NULL'), nullable=True)
    receiver_name = Column(String(80))
    accepted_quantity = Column(Numeric(12, 2))
    quality_accepted = Column(Boolean)
    delivery_notes = Column(Text)
    failure_reason = Column(String(255))
    reschedule_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
