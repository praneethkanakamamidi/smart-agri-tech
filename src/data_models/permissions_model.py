from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, TIMESTAMP
from src.db_connections.postgresql_conn import Base

class Permissions(Base):
    __tablename__="permissions"
    id = Column(Integer, primary_key=True, autoincrement=True)	
    permission_name = Column(String(30))
    permission_key = Column(String(50))
    created_time = Column(TIMESTAMP)
    updated_time = Column(TIMESTAMP)
    created_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    updated_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))