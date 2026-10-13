from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from src.db_connections.postgresql_conn import Base


class Crops(Base):
    """A produce item (tomato, onion, rice, ...)."""
    __tablename__ = "crops"
    __table_args__ = (Index("idx_crops_category", "category_id"),)

    id = Column(Integer, primary_key=True)
    crop_name = Column(String(100))
    crop_type = Column(String(50))
    description = Column(String(150))
    status = Column(Integer, ForeignKey('miscellaneous_data.id', ondelete='CASCADE'))
    created_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    updated_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    category_id = Column(Integer, ForeignKey('produce_categories.id', ondelete='SET NULL'), nullable=True)
    name_te = Column(String(100), nullable=True)
    default_unit = Column(String(20), nullable=True)

    status_rel = relationship("Miscellaneous_Data", foreign_keys=[status], lazy="raise")
    created_by_user = relationship("Users", foreign_keys=[created_by], lazy="raise")
    updated_by_user = relationship("Users", foreign_keys=[updated_by], lazy="raise")
    category_rel = relationship("ProduceCategories", foreign_keys=[category_id], lazy="raise")
