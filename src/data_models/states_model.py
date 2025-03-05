from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from src.db_connections.postgresql_conn import Base

class States(Base):
    __tablename__ = "states"
    
    id = Column(Integer, primary_key=True)
    state_name = Column(String(100))
    created_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    created_at = Column(DateTime)

