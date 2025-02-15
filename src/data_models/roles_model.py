from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, TIMESTAMP
from src.db_connections.postgresql_conn import Base

class Roles(Base):
    __tablename__="roles"
    
    id = Column(Integer, primary_key=True, autoincrement=True)		
    name = Column(String(30))
    status = Column(Integer, ForeignKey('miscellaneous_data.id', ondelete='CASCADE'))
    created_time = Column(TIMESTAMP)
    updated_time = Column(TIMESTAMP)
    created_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    updated_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
