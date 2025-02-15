from pydantic import BaseModel, SecretStr
from datetime import datetime
from typing import List


class Add_User(BaseModel):
    user_name:str =None
    first_name:str = None
    last_name:str= None
    password:SecretStr=None
    role_id:int =None
    created_by:int =None
    

class VerifyUserOtp(BaseModel):    
    user_name : str = None
    otp : SecretStr = None
