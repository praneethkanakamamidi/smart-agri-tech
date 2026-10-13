from sqlalchemy import Column, String, Integer, DateTime, Date, ForeignKey, Float, Index
from sqlalchemy.orm import relationship
from src.db_connections.postgresql_conn import Base


class FarmExpenses(Base):
    """Farmer's cost entries (seed, fertilizer, labour, ...) used for profit-per-crop."""
    __tablename__ = "farm_expenses"
    __table_args__ = (Index('idx_farm_expenses_farmer_date', 'farmer', 'expense_date'),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    farmer = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    crop = Column(Integer, ForeignKey('crops.id', ondelete='SET NULL'), nullable=True)
    category = Column(String(30), nullable=False)
    amount = Column(Float, nullable=False)
    expense_date = Column(Date, nullable=False)
    note = Column(String(255), nullable=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    crop_rel = relationship("Crops", foreign_keys=[crop], lazy="raise")
