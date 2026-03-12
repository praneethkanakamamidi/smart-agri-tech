from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from src.db_connections.postgresql_conn import Base


class Soil(Base):
    __tablename__ = "soil"

    id = Column(Integer, primary_key=True)
    soil_name = Column(String(10))
    soil_texture = Column(String(10))
    description = Column(String(150))
    status = Column(Integer, ForeignKey('miscellaneous_data.id', ondelete='CASCADE'))
    created_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    updated_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    status_rel = relationship("Miscellaneous_Data", foreign_keys=[status], lazy="raise")
    created_by_user = relationship("Users", foreign_keys=[created_by], lazy="raise")
    updated_by_user = relationship("Users", foreign_keys=[updated_by], lazy="raise")
