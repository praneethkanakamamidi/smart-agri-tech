from pydantic import BaseModel
from datetime import datetime
from typing import List

class Add_User(BaseModel):
    user_name:str =None
    first_name:str = None
    last_name:str= None
    password:str=None
    role_id:int =None
    created_by:int =None
