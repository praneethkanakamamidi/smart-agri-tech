from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from src.db_connections.postgresql_conn import Base

class FarmerInventory(Base):
    __tablename__ = "farmer_inventory"

    id = Column(Integer, primary_key=True)
    crop = Column(Integer, ForeignKey('crops.id', ondelete='CASCADE'))
    fertilizer = Column(Integer, ForeignKey('fertilizers.id', ondelete='CASCADE'))
    soil = Column(Integer, ForeignKey('soil.id', ondelete='CASCADE'))
    weight_kg = Column(Integer)
    proposed_cost = Column(Integer)
    description = Column(String(150))
    created_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    updated_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
