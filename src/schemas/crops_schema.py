from pydantic import BaseModel
from datetime import datetime
from typing import List

class CropsSchema(BaseModel):
    crop_name :str =None
    crop_type:str = None
    description:str= None
    created_by:int=None

class UpdateCropSchema(BaseModel):
    id:int=None
    crop_name :str =None
    crop_type:str = None
    description:str= None
    updated_by:int=None

class CropStatus(BaseModel):
    id:int=None
    updated_by:int=None
    
    
