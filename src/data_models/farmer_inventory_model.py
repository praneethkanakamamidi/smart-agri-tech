from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
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

    crop_rel = relationship("Crops", foreign_keys=[crop], lazy="raise")
    soil_rel = relationship("Soil", foreign_keys=[soil], lazy="raise")
    fertilizer_rel = relationship("Fertilizers", foreign_keys=[fertilizer], lazy="raise")
    created_by_user = relationship("Users", foreign_keys=[created_by], lazy="raise")
