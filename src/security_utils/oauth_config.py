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

# Initialize hashing utility and OAuth settings
hashing = Hashing()
oauth_settings = OAuthSettings()

class OAuth2Handler:
    """
    Handler class for managing OAuth2-based authentication.
    Provides methods for generating access and refresh tokens.
    """

    def generate_access_token(self, user: Users, access_token_secret_key: str, expiry_duration: timedelta) -> str:
        """
        Generate an access token for a given user.

        Args:
            user (Users): The user object containing user details.
            access_token_secret_key (str): Secret key used to sign the JWT.
            expiry_duration (timedelta): Expiry duration for the access token.

        Returns:
            str: The encoded JWT access token.
        """
        expiration_time = datetime.utcnow() + (expiry_duration if expiry_duration else self.access_expiry)
        token_data = {"uid": user.user_name, "exp": expiration_time.timestamp()}  # Convert datetime to timestamp
        return jwt.encode(token_data, access_token_secret_key, algorithm=self.algorithm)

    def generate_refresh_token(self, user: Users, expiry_duration: timedelta = None) -> str:
        """
        Generate a refresh token for a given user.

        Args:
            user (Users): The user object containing user details.
            expiry_duration (timedelta, optional): Expiry duration for the refresh token. Defaults to None.

        Returns:
            str: The encoded JWT refresh token.
        """
        expiration_time = datetime.utcnow() + (expiry_duration if expiry_duration else self.refresh_expiry)
        token_data = {"uid": user.user_name, "exp": expiration_time.timestamp()}  # Convert datetime to timestamp
        return jwt.encode(token_data, self.refresh_token_secret_key, algorithm=self.algorithm)