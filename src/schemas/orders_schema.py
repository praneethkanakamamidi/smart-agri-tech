from pydantic import BaseModel
from datetime import datetime
from typing import List

class PostOrderSchema(BaseModel):
    stock_id:int=None
    vendor:int=None
    quantity:int=None

class UpdateOrderStatus(BaseModel):
    order_id:int=None
    status:str=None
    user_id:int=None