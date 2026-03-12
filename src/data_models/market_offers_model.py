from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Float
from sqlalchemy.orm import relationship
from src.db_connections.postgresql_conn import Base


class MarketOffers(Base):
    """
    Tracks vendor bargain offers on farmer's market listings.
    Farmer can accept, reject, or counter. Vendor can send new offers.
    When accepted, an order is created with the agreed price.
    """
    __tablename__ = "market_offers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    farmer_inventory = Column(Integer, ForeignKey('farmer_inventory.id', ondelete='CASCADE'))
    vendor = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    farmer = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    vendor_offer_price = Column(Float)  # Vendor's proposed price per kg
    farmer_counter_price = Column(Float, nullable=True)  # Farmer's counter when status='countered'
    quantity_kg = Column(Float)
    message = Column(String(255), nullable=True)  # Optional note from vendor
    status = Column(String(20))  # pending | accepted | rejected | countered
    order_id = Column(Integer, ForeignKey('orders.id', ondelete='SET NULL'), nullable=True)  # Set when accepted
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    farmer_inventory_rel = relationship("FarmerInventory", foreign_keys=[farmer_inventory], lazy="raise")
    vendor_user = relationship("Users", foreign_keys=[vendor], lazy="raise")
    farmer_user = relationship("Users", foreign_keys=[farmer], lazy="raise")
