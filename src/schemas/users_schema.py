from pydantic import BaseModel
from datetime import datetime
from typing import List

class Add_User(BaseModel):
    emp_id :str  = None 
    user_name:str =None
    first_name:str = None
    last_name:str= None
    role_id:int =None 
    team_lead_id:int = None
    created_by_id:int =None
