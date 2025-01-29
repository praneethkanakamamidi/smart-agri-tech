from sqlalchemy.orm import Session
from passlib.context import CryptContext
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from src.data_models.users_model import User
from sqlalchemy import desc, func
from sqlalchemy import func,and_
from src.db_connections.postgresql_conn import get_db
import jwt
import time


class Users_Service():
    def add_user(self, payload):
        db=next(get_db())
        try:
            return "task pending..."
        finally:
            db.close()
            