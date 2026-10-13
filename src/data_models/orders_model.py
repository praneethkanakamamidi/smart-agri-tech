from sqlalchemy import Column, String, Integer, DateTime, Date, ForeignKey, Numeric, JSON, Text, Index
from sqlalchemy.orm import relationship
from src.db_connections.postgresql_conn import Base

# Order lifecycle (values of miscellaneous_data where category = 'order_status')
PENDING_CONFIRMATION = "pending_confirmation"
CONFIRMED = "confirmed"
PREPARING = "preparing"
READY_FOR_PICKUP = "ready_for_pickup"
IN_TRANSIT = "in_transit"
DELIVERED = "delivered"
COMPLETED = "completed"
CANCELLED = "cancelled"
DELIVERY_FAILED = "delivery_failed"
DISPUTED = "disputed"
REFUND_PENDING = "refund_pending"
REFUNDED = "refunded"

ORDER_STATUSES = (
    PENDING_CONFIRMATION, CONFIRMED, PREPARING, READY_FOR_PICKUP, IN_TRANSIT, DELIVERED,
    COMPLETED, CANCELLED, DELIVERY_FAILED, DISPUTED, REFUND_PENDING, REFUNDED,
)
# Orders that represent a real agreed deal for price statistics.
DEAL_STATUSES = (CONFIRMED, PREPARING, READY_FOR_PICKUP, IN_TRANSIT, DELIVERED, COMPLETED, DISPUTED)
ACTIVE_STATUSES = (PENDING_CONFIRMATION, CONFIRMED, PREPARING, READY_FOR_PICKUP, IN_TRANSIT, DELIVERY_FAILED)

# Payment terms
FULL_ADVANCE = "full_advance"
PARTIAL_ADVANCE = "partial_advance"
PAY_BEFORE_DISPATCH = "pay_before_dispatch"
PAY_ON_DELIVERY = "pay_on_delivery"
CASH_ON_DELIVERY = "cash_on_delivery"
PAYMENT_TERMS = (FULL_ADVANCE, PARTIAL_ADVANCE, PAY_BEFORE_DISPATCH, PAY_ON_DELIVERY, CASH_ON_DELIVERY)

# Fulfilment modes
PICKUP = "pickup"  # vendor collects at the farm
FARMER_DELIVERY = "farmer_delivery"
VENDOR_TRANSPORT = "vendor_transport"
THIRD_PARTY = "third_party"
FULFILLMENT_MODES = (PICKUP, FARMER_DELIVERY, VENDOR_TRANSPORT, THIRD_PARTY)


class Orders(Base):
    """
    An accepted commercial transaction. The agreed terms are stored on the order
    (and frozen in terms_snapshot) - never recomputed from the listing's current price.
    """
    __tablename__ = "orders"
    __table_args__ = (
        Index("idx_orders_farmer", "farmer"),
        Index("idx_orders_vendor", "vendor"),
        Index("uq_orders_order_number", "order_number", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    farmer_inventory = Column(Integer, ForeignKey('farmer_inventory.id', ondelete='CASCADE'))
    vendor = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    farmer = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    quantity_kg = Column(Numeric(12, 2))  # agreed quantity in `unit`
    total_price = Column(Numeric(14, 2))  # final payable amount
    status = Column(Integer, ForeignKey('miscellaneous_data.id', ondelete='CASCADE'))
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    order_number = Column(String(30))
    unit = Column(String(20), default="kg")
    unit_price = Column(Numeric(12, 2))
    subtotal = Column(Numeric(14, 2))
    packaging_charge = Column(Numeric(12, 2), default=0)
    transport_charge = Column(Numeric(12, 2), default=0)
    platform_fee = Column(Numeric(12, 2), default=0)
    tax_amount = Column(Numeric(12, 2), default=0)
    discount_amount = Column(Numeric(12, 2), default=0)
    payment_terms = Column(String(30))
    advance_amount = Column(Numeric(14, 2), default=0)
    fulfillment_mode = Column(String(30))
    delivery_instructions = Column(Text)
    expected_delivery_date = Column(Date)
    negotiation_id = Column(Integer, ForeignKey('negotiations.id', ondelete='SET NULL'), nullable=True)
    offer_id = Column(Integer, ForeignKey('offers.id', ondelete='SET NULL'), nullable=True)
    source = Column(String(30))  # negotiation | direct | buy_request | recurring | legacy
    terms_snapshot = Column(JSON)
    agreed_at = Column(DateTime)
    farmer_confirmed_at = Column(DateTime)
    vendor_confirmed_at = Column(DateTime)
    confirmation_deadline = Column(DateTime)
    cancel_reason = Column(String(255))
    cancelled_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    cancelled_at = Column(DateTime)
    cancel_requested_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    cancel_request_reason = Column(String(255))
    cancel_requested_at = Column(DateTime)
    status_before_dispute = Column(String(30))
    delivered_at = Column(DateTime)
    completed_at = Column(DateTime)

    farmer_inventory_rel = relationship("FarmerInventory", foreign_keys=[farmer_inventory], lazy="raise")
    vendor_user = relationship("Users", foreign_keys=[vendor], lazy="raise")
    farmer_user = relationship("Users", foreign_keys=[farmer], lazy="raise")
    status_rel = relationship("Miscellaneous_Data", foreign_keys=[status], lazy="raise")
    transactions = relationship("Transactions", back_populates="order_rel", lazy="raise")


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('orders.id', ondelete='CASCADE'), nullable=False)
    from_status = Column(String(30))
    to_status = Column(String(30), nullable=False)
    actor_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)  # null = system
    note = Column(String(255))
    created_at = Column(DateTime)


class OrderAdjustments(Base):
    """Authorised correction to an order's payable amount. The original terms are never rewritten."""
    __tablename__ = "order_adjustments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('orders.id', ondelete='CASCADE'), nullable=False)
    amount = Column(Numeric(14, 2), nullable=False)  # + increases payable, - decreases
    reason = Column(String(500), nullable=False)
    created_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime)


class Invoices(Base):
    """Order receipts, payment receipts and invoices with sequential numbering."""
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('orders.id', ondelete='CASCADE'), nullable=False)
    transaction_id = Column(Integer, ForeignKey('transactions.id', ondelete='SET NULL'), nullable=True)
    invoice_number = Column(String(30), unique=True, nullable=False)
    invoice_type = Column(String(20), nullable=False)  # order_receipt | payment_receipt | invoice
    total_amount = Column(Numeric(14, 2), nullable=False)
    data = Column(JSON, nullable=False)  # frozen document content
    issued_at = Column(DateTime)
