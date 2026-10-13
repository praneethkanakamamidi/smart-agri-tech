from pydantic import BaseModel

class FertilizerSchema(BaseModel):
    fertilizer_name :str =None
    application_method:str = None
    description:str= None
    created_by:int=None


class UpdateFertilizerSchema(BaseModel):
    id:int=None
    fertilizer_name :str =None
    application_method:str = None
    description:str= None
    updated_by:int=None

class FertilizerStatus(BaseModel):
    id:int=None
    updated_by:int=None 