from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, TIMESTAMP
from src.db_connections.postgresql_conn import Base
from sqlalchemy.orm import relationship

class Users(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    user_name = Column(String(50))
    first_name = Column(String(30))
    last_name = Column(String(30))
    password = Column(String(150))
    status = Column(Integer, ForeignKey('miscellaneous_data.id', ondelete='CASCADE'))
    role_id = Column(Integer, ForeignKey('roles.id', ondelete='CASCADE'))
    state = Column(Integer, ForeignKey('states.id', ondelete='CASCADE'))
    district = Column(Integer, ForeignKey('districts.id', ondelete='CASCADE'))
    created_time = Column(TIMESTAMP)
    updated_time = Column(TIMESTAMP)
    updated_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))

