from pydantic import BaseModel
from datetime import datetime
from typing import List

class PostOrderSchema(BaseModel):
    stock_id :int =None
    amount:int = None

class UpdateOrderStatus(BaseModel):
    order_id: int = None
    user_id: int = None