from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Index, func, text
from src.db_connections.postgresql_conn import Base


class Districts(Base):
    """Seeded by `python -m src.seeds`."""
    __tablename__ = "districts"
    __table_args__ = (
        Index("uq_districts_state_name", "state_id", func.lower(func.btrim(text("district_name"))), unique=True),
    )

    id = Column(Integer, primary_key=True)
    district_name = Column(String(100), nullable=False)
    state_id = Column(Integer, ForeignKey('states.id', ondelete='CASCADE'))
    created_by = Column(Integer)  # no FK: reference data is system-owned (NULL for seeded rows)
    created_at = Column(DateTime)
