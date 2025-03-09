from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from src.db_connections.postgresql_conn import Base

class Transactions(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey('orders.id', ondelete='CASCADE'))
    razorpay_order_id = Column(String, nullable=False, unique=True)
    razorpay_payment_id = Column(String, nullable=True, unique=True)
    razorpay_signature = Column(String, nullable=True)
    amount_paid = Column(Integer, nullable=False)
    currency = Column(String)
    status = Column(Integer, ForeignKey('miscellaneous_data.id', ondelete='CASCADE'))
    created_at = Column(DateTime)
