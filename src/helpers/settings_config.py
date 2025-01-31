import os
from pydantic_settings import BaseSettings


class OAuthSettings(BaseSettings):
    # Authentication variables
    ACCESS_TOKEN: str
    REFRESH_TOKEN: str
    ALGORITHM: str
    ACCESS_EXPIRY: int = 30
    REFRESH_EXPIRY: int = 10080  # Default to 60*24*7

