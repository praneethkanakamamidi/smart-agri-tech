from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Float, Index
from sqlalchemy.orm import relationship
from src.db_connections.postgresql_conn import Base


class MarketOffers(Base):
    """
    Tracks vendor bargain offers on farmer's market listings.
    Farmer can accept, reject, or counter. Vendor can send new offers.
    When accepted, an order is created with the agreed price.
    """
    __tablename__ = "market_offers"
    __table_args__ = (
        Index("idx_market_offers_farmer", "farmer"),
        Index("idx_market_offers_vendor", "vendor"),
        Index("idx_market_offers_inventory", "farmer_inventory"),
        Index("idx_market_offers_status", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    farmer_inventory = Column(Integer, ForeignKey('farmer_inventory.id', ondelete='CASCADE'), nullable=False)
    vendor = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    farmer = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    vendor_offer_price = Column(Float, nullable=False)  # Vendor's proposed price per kg
    farmer_counter_price = Column(Float, nullable=True)  # Farmer's counter when status='countered'
    quantity_kg = Column(Float, nullable=False)
    message = Column(String(255), nullable=True)  # Optional note from vendor
    status = Column(String(20), nullable=False)  # pending | accepted | rejected | countered
    order_id = Column(Integer, ForeignKey('orders.id', ondelete='SET NULL'), nullable=True)  # Set when accepted
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    farmer_inventory_rel = relationship("FarmerInventory", foreign_keys=[farmer_inventory], lazy="raise")
    vendor_user = relationship("Users", foreign_keys=[vendor], lazy="raise")
    farmer_user = relationship("Users", foreign_keys=[farmer], lazy="raise")
