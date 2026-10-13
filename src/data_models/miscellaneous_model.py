from sqlalchemy import Column, String, Integer, DateTime, Index
from src.db_connections.postgresql_conn import Base


class Miscellaneous_Data(Base):
    """Lookup values (statuses, answers). Seeded by `python -m src.seeds`."""
    __tablename__ = "miscellaneous_data"
    __table_args__ = (
        Index("uq_miscellaneous_data_category_value", "category", "value", unique=True),
    )

    id = Column(Integer, primary_key=True)
    category = Column(String(50))
    value = Column(String(150))
    # Audit columns without FK constraints: users references this table, so FKs here would be circular.
    created_by = Column(Integer)
    updated_by = Column(Integer)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
