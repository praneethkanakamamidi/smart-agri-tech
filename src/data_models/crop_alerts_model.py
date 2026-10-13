from sqlalchemy import Column, Integer, DateTime, ForeignKey, Float, Boolean, Index
from sqlalchemy.orm import relationship
from src.db_connections.postgresql_conn import Base


class CropAlerts(Base):
    """
    A vendor's saved search. When a farmer lists stock matching it,
    the vendor gets an in-app notification.
    """
    __tablename__ = "crop_alerts"
    __table_args__ = (
        Index('idx_crop_alerts_crop_active', 'crop', 'is_active'),
        Index('idx_crop_alerts_vendor', 'vendor'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    vendor = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    crop = Column(Integer, ForeignKey('crops.id', ondelete='CASCADE'), nullable=False)
    state = Column(Integer, ForeignKey('states.id', ondelete='CASCADE'), nullable=True)
    district = Column(Integer, ForeignKey('districts.id', ondelete='CASCADE'), nullable=True)
    min_quantity_kg = Column(Float, nullable=True)
    max_price_per_kg = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime)

    crop_rel = relationship("Crops", foreign_keys=[crop], lazy="raise")
