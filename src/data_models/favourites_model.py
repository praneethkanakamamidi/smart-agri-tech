from sqlalchemy import Column, Integer, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from src.db_connections.postgresql_conn import Base


class FavouriteFarmers(Base):
    """A vendor following a farmer to see their new stock first."""
    __tablename__ = "favourite_farmers"
    __table_args__ = (
        UniqueConstraint('vendor', 'farmer', name='uq_favourite_farmers_vendor_farmer'),
        Index('idx_favourite_farmers_farmer', 'farmer'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    vendor = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    farmer = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    created_at = Column(DateTime)

    farmer_user = relationship("Users", foreign_keys=[farmer], lazy="raise")
