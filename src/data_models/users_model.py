from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, TIMESTAMP
from src.db_connections.postgresql_conn import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    user_name = Column(String(50))
    first_name = Column(String(30))
    last_name = Column(String(30))
    password = Column(String(150))
    status = Column(Integer)
    role_id = Column(Integer)
    created_time = Column(TIMESTAMP)
    updated_time = Column(TIMESTAMP)
    created_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    updated_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
