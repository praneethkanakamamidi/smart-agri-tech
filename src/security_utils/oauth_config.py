# main.py
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import sessionmaker
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import Optional, Union, Any
from app.model.users import Users
from fastapi import APIRouter, Depends
from src.security_utils.hashing_config import Hashing
import secrets
import os

hashing = Hashing()

access_token_secret_key  = os.getenv("ACCESS_TOKEN_SECRET_KEY ")
refresh_token_secret_key  = os.getenv("REFRESH_TOKEN_SECRET_KEY ")
algorithm  = os.getenv("ALGORITHM")
access_expiry  = 30
refresh_expiry = 60 * 24 * 7

def generate_access_token(data: dict, expiry_duration : timedelta = None):
    token_data  = data.copy()
    if expiry_duration :
        expiration_time  = datetime.utcnow() + expiry_duration 
    else:
        expiration_time  = datetime.utcnow() + timedelta(access_expiry)
    token_data .update({"exp": expiration_time })
    encoded_token  = jwt.encode(token_data , access_token_secret_key, algorithm=algorithm)
    return encoded_token 

def generate_refresh_token(data: dict, expiry_duration : timedelta = None):
    token_data  = data.copy()
    if expiry_duration :
        expiration_time  = datetime.utcnow() + expiry_duration 
    else:
        expiration_time  = datetime.utcnow() + timedelta(refresh_token_secret_key)
    token_data .update({"exp": expiration_time })
    encoded_token  = jwt.encode(token_data , refresh_expiry, algorithm=algorithm)
    return encoded_token 

