# main.py
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import sessionmaker
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import Optional, Union, Any
from src.data_models.users_model import Users
from fastapi import APIRouter, Depends
from src.security_utils.hashing_config import Hashing
from src.helpers.settings_config import OAuthSettings
import secrets
import os

hashing = Hashing()
oauth_settings = OAuthSettings() 

class OAuth2Handler:
    def __init__(self):
        self.access_token_secret_key = oauth_settings.access_token_secret_key
        self.refresh_token_secret_key = oauth_settings.refresh_token_secret_key
        self.algorithm = oauth_settings.algorithm
        self.access_expiry = timedelta(minutes=oauth_settings.access_expiry)
        self.refresh_expiry = timedelta(minutes=oauth_settings.refresh_expiry)

    def generate_access_token(self, data: dict, expiry_duration: timedelta = None) -> str:
        token_data = data.copy()
        expiration_time = datetime.utcnow() + (expiry_duration if expiry_duration else self.access_expiry)
        token_data.update({"exp": expiration_time})
        return jwt.encode(token_data, self.access_token_secret_key, algorithm=self.algorithm)

    def generate_refresh_token(self, data: dict, expiry_duration: timedelta = None) -> str:
        token_data = data.copy()
        expiration_time = datetime.utcnow() + (expiry_duration if expiry_duration else self.refresh_expiry)
        return jwt.encode(token_data, self.refresh_token_secret_key, algorithm=self.algorithm)
