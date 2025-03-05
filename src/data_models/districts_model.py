from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from src.db_connections.postgresql_conn import Base

class Districts(Base):
    __tablename__ = "districts"
    
    id = Column(Integer, primary_key=True)
    district_name = Column(String(100))
    state_id = Column(Integer, ForeignKey('states.id', ondelete='CASCADE'))
    created_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    created_at = Column(DateTime)