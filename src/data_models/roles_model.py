from sqlalchemy import Column, String, Integer, ForeignKey, TIMESTAMP, Index, func, text
from src.db_connections.postgresql_conn import Base


class Roles(Base):
    __tablename__ = "roles"
    __table_args__ = (
        Index("uq_roles_name", func.lower(func.btrim(text("name"))), unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(30))
    status = Column(Integer, ForeignKey('miscellaneous_data.id', ondelete='CASCADE'))
    created_time = Column(TIMESTAMP)
    updated_time = Column(TIMESTAMP)
    # Audit columns without FK constraints: users references this table, so FKs here would be circular.
    created_by = Column(Integer)
    updated_by = Column(Integer)
