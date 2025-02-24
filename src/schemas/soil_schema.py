from pydantic import BaseModel
from datetime import datetime
from typing import List

class SoilSchema(BaseModel):
    soil_name :str =None
    soil_texture:str = None
    description:str= None
    created_by:int=None


class UpdateSoilSchema(BaseModel):
    id:int=None
    soil_name :str =None
    soil_texture:str = None
    description:str= None
    updated_by:int=None

class SoilStatus(BaseModel):
    id:int=None
    updated_by:int=None
    
