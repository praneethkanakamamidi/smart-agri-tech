from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Float
from sqlalchemy.orm import relationship
from src.db_connections.postgresql_conn import Base


class Orders(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    farmer_inventory = Column(Integer, ForeignKey('farmer_inventory.id', ondelete='CASCADE'))
    vendor = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    farmer = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    quantity_kg = Column(Float)
    total_price = Column(Integer)
    status = Column(Integer, ForeignKey('miscellaneous_data.id', ondelete='CASCADE'))
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    farmer_inventory_rel = relationship("FarmerInventory", foreign_keys=[farmer_inventory], lazy="raise")
    vendor_user = relationship("Users", foreign_keys=[vendor], lazy="raise")
    farmer_user = relationship("Users", foreign_keys=[farmer], lazy="raise")
    status_rel = relationship("Miscellaneous_Data", foreign_keys=[status], lazy="raise")
    transactions = relationship("Transactions", back_populates="order_rel", lazy="raise")
