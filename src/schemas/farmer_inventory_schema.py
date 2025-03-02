from pydantic import BaseModel
from datetime import datetime
from typing import List

class AddFarmerInventorySchema(BaseModel):
    crop:int=None
    fertilizer:int=None
    soil:int=None
    weight_kg:int=None
    proposed_cost:int=None
    description:str=None
    created_by:int=None
    
class UpdateFarmerInventorySchema(BaseModel):
    id:int=None
    crop:int=None
    fertilizer:int=None
    soil:int=None
    weight_kg:int=None
    proposed_cost:int=None
    description:str=None
    updated_by:int=None

