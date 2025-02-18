from pydantic import BaseModel
from datetime import datetime
from typing import List

class FertilizerSchema(BaseModel):
    fetilizer_name :str =None
    application_method:str = None
    description:str= None
    created_by:int=None


class UpdateFertilizerSchema(BaseModel):
    id:int=None
    fetilizer_name :str =None
    application_method:str = None
    description:str= None
    updated_by:int=None

class FertilizerStatus(BaseModel):
    id:int=None
    updated_by:int=None 