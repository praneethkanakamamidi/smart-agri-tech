from sqlalchemy import Column, String, Integer, DateTime, Index, UniqueConstraint, func, text
from src.db_connections.postgresql_conn import Base


class States(Base):
    """Seeded by `python -m src.seeds`."""
    __tablename__ = "states"
    __table_args__ = (
        UniqueConstraint("state_name", name="states_state_name_key"),
        Index("uq_states_name_ci", func.lower(func.btrim(text("state_name"))), unique=True),
    )

    id = Column(Integer, primary_key=True)
    state_name = Column(String(100), nullable=False)
    created_by = Column(Integer)  # no FK: reference data is system-owned (NULL for seeded rows)
    created_at = Column(DateTime)
