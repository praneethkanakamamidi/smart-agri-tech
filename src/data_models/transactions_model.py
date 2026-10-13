from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Numeric, JSON
from sqlalchemy.orm import relationship
from src.db_connections.postgresql_conn import Base

# Transaction status values (miscellaneous_data category 'payment_status') and their API names.
PAYMENT_STATE_NAMES = {
    "initiated": "INITIATED",
    "pending": "PENDING",
    "paid": "SUCCESS",
    "failed": "FAILED",
    "refund_pending": "REFUND_PENDING",
    "refunded": "REFUNDED",
}


class Transactions(Base):
    """A payment attempt against an order (gateway, UPI, bank transfer or cash)."""
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('orders.id', ondelete='CASCADE'))
    razorpay_order_id = Column(String, nullable=True, unique=True)
    razorpay_payment_id = Column(String, nullable=True, unique=True)
    razorpay_signature = Column(String, nullable=True)
    amount_paid = Column(Numeric(14, 2), nullable=False)
    currency = Column(String)
    status = Column(Integer, ForeignKey('miscellaneous_data.id', ondelete='CASCADE'))
    created_at = Column(DateTime)

    payment_method = Column(String(20), default="gateway")  # gateway | upi | bank_transfer | cash
    purpose = Column(String(20), default="full")  # full | advance | balance
    reference = Column(String(100))  # external/UTR reference for manual payments
    failure_reason = Column(String(255))
    verified_via = Column(String(30))  # client_signature | webhook | reconciliation | farmer_confirmation
    recorded_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    updated_at = Column(DateTime)

    status_rel = relationship("Miscellaneous_Data", foreign_keys=[status], lazy="raise")
    order_rel = relationship("Orders", back_populates="transactions", lazy="raise")


class Refunds(Base):
    """Refund / financial adjustment. Never edits the original payment record."""
    __tablename__ = "refunds"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('orders.id', ondelete='CASCADE'), nullable=False)
    transaction_id = Column(Integer, ForeignKey('transactions.id', ondelete='SET NULL'), nullable=True)
    dispute_id = Column(Integer, ForeignKey('disputes.id', ondelete='SET NULL'), nullable=True)
    amount = Column(Numeric(14, 2), nullable=False)
    reason = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False)  # REFUND_PENDING | REFUNDED | FAILED
    gateway_refund_id = Column(String(60))
    reference = Column(String(100))
    failure_reason = Column(String(255))
    initiated_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime)
    processed_at = Column(DateTime)


class Settlements(Base):
    """What the platform owes the farmer for a completed order."""
    __tablename__ = "settlements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('orders.id', ondelete='CASCADE'), unique=True, nullable=False)
    farmer = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    gross_amount = Column(Numeric(14, 2), nullable=False)
    fee_deducted = Column(Numeric(14, 2), default=0, nullable=False)
    adjustments = Column(Numeric(14, 2), default=0, nullable=False)
    collected_directly = Column(Numeric(14, 2), default=0, nullable=False)  # cash the farmer already received
    net_amount = Column(Numeric(14, 2), nullable=False)
    status = Column(String(20), nullable=False)  # pending | paid | on_hold
    payout_reference = Column(String(100))
    created_at = Column(DateTime)
    paid_at = Column(DateTime)


class WebhookEvents(Base):
    """Received provider callbacks, for idempotent processing."""
    __tablename__ = "webhook_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(20), nullable=False)
    event_id = Column(String(100), unique=True, nullable=False)
    event_type = Column(String(60))
    payload = Column(JSON)
    status = Column(String(20))  # processed | ignored | failed
    error = Column(String(255))
    received_at = Column(DateTime)
