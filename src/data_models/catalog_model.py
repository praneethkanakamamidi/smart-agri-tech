from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Numeric, Boolean
from src.db_connections.postgresql_conn import Base


class ProduceCategories(Base):
    """Product taxonomy: vegetables, fruits, grains, pulses, ..."""
    __tablename__ = "produce_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(60), unique=True, nullable=False)
    name_te = Column(String(60))
    parent_id = Column(Integer, ForeignKey('produce_categories.id', ondelete='SET NULL'), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime)


class Units(Base):
    """Units of measurement. kg_factor converts a quantity in this unit to kg (null if not mass-based)."""
    __tablename__ = "units"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), unique=True, nullable=False)  # kg | quintal | tonne | bag | crate
    name = Column(String(40), nullable=False)
    name_te = Column(String(40))
    kg_factor = Column(Numeric(12, 4), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)


class QualityStandards(Base):
    """Standardised quality grades a listing can claim."""
    __tablename__ = "quality_standards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), unique=True, nullable=False)  # A | B | C
    name = Column(String(40), nullable=False)
    name_te = Column(String(40))
    description = Column(String(255))
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True, nullable=False)
