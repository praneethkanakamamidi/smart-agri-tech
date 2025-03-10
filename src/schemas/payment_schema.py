from pydantic import BaseModel
from datetime import datetime
from typing import List

class CreatePayment(BaseModel):
    order_id:int=None
    amount_paid:int=None
    currency:str=None

class VerifyPayment(BaseModel):
    razorpay_order_id:str=None
    razorpay_payment_id:str=None
    razorpay_signature:str=None