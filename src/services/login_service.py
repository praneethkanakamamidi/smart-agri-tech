from fastapi import HTTPException
from sqlalchemy.orm import Session
from jose import jwt
from datetime import timedelta, datetime
from src.data_models.users_model import Users
from src.data_models.miscellaneous_model import Miscellaneous_Data
from src.security_utils.hashing_config import Hashing
from src.helpers.settings_config import OAuthSettings

hashing = Hashing()
oauth_settings = OAuthSettings()

class LoginService:
    def __init__(self):
        self.access_token_secret_key = oauth_settings.ACCESS_TOKEN
        self.refresh_token_secret_key = oauth_settings.REFRESH_TOKEN
        self.algorithm = oauth_settings.ALGORITHM
        self.access_expiry = timedelta(minutes=oauth_settings.ACCESS_EXPIRY)
        self.refresh_expiry = timedelta(minutes=oauth_settings.REFRESH_EXPIRY)

    def login(self, form_data, db: Session):
        """Handles login functionality, checking user credentials, and issuing tokens."""
        # Get user from DB
        user = self.get_user_by_username(form_data.username, db)
        
        # Check if user is active
        self.check_user_status(user, db)
        
        # Create access and refresh tokens
        access_token, refresh_token = self.create_tokens(user)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "id": user.id,
        }

    def get_user_by_username(self, username: str, db: Session) -> Users:
        """Fetch user from DB by username."""
        user = db.query(Users).filter(Users.user_name == username).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user

    def check_user_status(self, user: Users, db: Session):
        """Check if user is active in the system."""
        is_active = db.query(Miscellaneous_Data.id).filter(Miscellaneous_Data.category == "status").filter(Miscellaneous_Data.value == "inactive").first()
        if user.status == is_active[0]:
            raise HTTPException(status_code=401, detail="User is InActive")

    def generate_token(self, user: Users, secret_key: str, expires_delta: timedelta):
        """Generate JWT token with 'sub' and 'exp' claims."""
        expiration = datetime.utcnow() + expires_delta
        token_data = {"sub": user.user_name, "exp": expiration}
        return jwt.encode(token_data, secret_key, algorithm=self.algorithm)

    def create_tokens(self, user: Users):
        """Create both access and refresh tokens."""
        access_token = self.generate_token(user, self.access_token_secret_key, self.access_expiry)
        refresh_token = self.generate_token(user, self.refresh_token_secret_key, self.refresh_expiry)
        return access_token, refresh_token

    def get_current_user(self, token: str, db: Session) -> Users:
        """Authenticate and get the user based on the provided JWT token."""
        credentials_exception = HTTPException(
            status_code=401,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
        try:
            payload = jwt.decode(token, oauth_settings.ACCESS_TOKEN, algorithms=[oauth_settings.ALGORITHM])
            user_name: str = payload.get("sub")

            if datetime.fromtimestamp(payload['exp']) < datetime.now():
                raise HTTPException(
                    status_code=401,
                    detail="Token expired",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            
            if user_name is None:
                raise credentials_exception

            user = db.query(Users).filter(Users.user_name == user_name).first()
            if user is None:
                raise credentials_exception

            return user
        except jwt.ExpiredSignatureError:  # Handle expired token
            raise HTTPException(
                status_code=401,
                detail="Token has expired",
            )
