from pydantic import BaseModel, Field


class Model_Schema(BaseModel):
    """Soil nutrients and climate readings for crop recommendation. All fields are required."""
    N: float = Field(..., ge=0, le=1000, description="Nitrogen content of the soil")
    P: float = Field(..., ge=0, le=1000, description="Phosphorus content of the soil")
    K: float = Field(..., ge=0, le=1000, description="Potassium content of the soil")
    temperature: float = Field(..., ge=-20, le=60, description="Temperature in °C")
    humidity: float = Field(..., ge=0, le=100, description="Relative humidity in %")
    ph: float = Field(..., ge=0, le=14, description="Soil pH")
    rainfall: float = Field(..., ge=0, le=10000, description="Rainfall in mm")
