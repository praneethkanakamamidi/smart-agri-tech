from pydantic import BaseModel
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from src.db_connections.postgresql_conn import Base
from datetime import datetime

class Miscellaneous_Data(Base):
    __tablename__ = "miscellaneous_data"
    
    id = Column(Integer, primary_key=True)
    category = Column(String(10))
    value = Column(String(150))
    created_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    updated_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    
    