from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Float
from src.db_connections.postgresql_conn import Base

class Orders(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    farmer_inventory_id = Column(Integer, ForeignKey('farmer_inventory.id', ondelete='CASCADE'))
    vendor_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    farmer_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    quantity_kg = Column(Float)
    total_price = Column(Integer)
    status = Column(Integer, ForeignKey('miscellaneous_data.id', ondelete='CASCADE'))
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
