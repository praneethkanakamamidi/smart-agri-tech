from pydantic import BaseModel
from datetime import datetime
from typing import List

class Model_Schema(BaseModel):
    N:int =None
    P:int = None
    K:int= None
    temperature:float=None
    humidity:float =None
    ph:float =None
    rainfall:float=None
