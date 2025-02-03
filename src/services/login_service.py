from fastapi import HTTPException, Depends, status
from sqlalchemy.orm import Session
from jose import jwt
from datetime import timedelta, datetime
from src.data_models.users_model import Users
from src.data_models.miscellaneous_model import Miscellaneous_Data
from src.security_utils.hashing_config import Hashing
from src.helpers.settings_config import OAuthSettings
from fastapi.security import OAuth2PasswordBearer
from src.db_connections.postgresql_conn import get_db
from src.security_utils.oauth_config import OAuth2Handler

# Initialize utilities and settings
hashing = Hashing()
oauth_settings = OAuthSettings()


# Define OAuth2 password bearer scheme for authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")


class LoginService(OAuth2Handler):
    """Service class responsible for user authentication and token management."""

    def __init__(self):
        """
        Initializes the LoginService with security settings.

        Attributes:
            access_token_secret_key (str): Secret key for signing access tokens.
            refresh_token_secret_key (str): Secret key for signing refresh tokens.
            algorithm (str): Algorithm used for token encryption.
            access_expiry (timedelta): Expiration time for access tokens.
            refresh_expiry (timedelta): Expiration time for refresh tokens.
        """
        self.access_token_secret_key = oauth_settings.ACCESS_TOKEN
        self.refresh_token_secret_key = oauth_settings.REFRESH_TOKEN
        self.algorithm = oauth_settings.ALGORITHM
        self.access_expiry = timedelta(minutes=oauth_settings.ACCESS_EXPIRY)
        self.refresh_expiry = timedelta(minutes=oauth_settings.REFRESH_EXPIRY)

    def login(self, form_data, db: Session):
        """
        Authenticates a user based on provided credentials and issues JWT tokens.

        :param form_data: Contains the user's login credentials (username & password).
        :param db: SQLAlchemy database session.
        :return: A dictionary containing the access and refresh tokens.

        :raises HTTPException 404: If the user does not exist.
        :raises HTTPException 401: If the password is incorrect.
        :raises HTTPException 403: If the user account is inactive.
        """
        # Retrieve user record from the database
        user_data = db.query(Users).filter(Users.user_name == form_data.username).first()
        if not user_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found: Enter valid user details",
                headers={"Content-Type": "application/json"}
            )
        
        # Validate password
        if not hashing.verify_password(form_data.password, user_data.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed: The provided password is incorrect",
                headers={"Content-Type": "application/json"}
            )

        # Check if the user account is active
        active_data = db.query(Miscellaneous_Data).filter(
            Miscellaneous_Data.category == "status",
            Miscellaneous_Data.value == "active"
        ).first()

        if user_data.status != active_data.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: The user account is inactive. Contact support for assistance.",
                headers={"Content-Type": "application/json"}
            )

        # Generate authentication tokens using the inherited methods
        access_token = self.generate_access_token(user_data, self.access_token_secret_key, self.access_expiry)
        refresh_token = self.generate_refresh_token(user_data, self.refresh_expiry)

        return {
            "status": "success",
            "access_token": access_token,
            "refresh_token": refresh_token,
        }


    def get_current_active_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
        """
        Retrieves the currently authenticated active user from the JWT token.

        :param token: JWT token provided in the Authorization header.
        :param db: SQLAlchemy database session.
        :return: The authenticated active user.

        :raises HTTPException 401: If the token is expired or invalid.
        :raises HTTPException 401: If the username is missing in the token.
        :raises HTTPException 401: If the user does not exist in the system.
        """
        try:
            # Decode JWT token
            payload = jwt.decode(token, oauth_settings.ACCESS_TOKEN, algorithms=[oauth_settings.ALGORITHM])
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=401,
                detail="Authentication failed: Token has expired. Please log in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except jwt.InvalidTokenError:
            raise HTTPException(
                status_code=401,
                detail="Authentication failed: Invalid token. Ensure you provide a valid authentication token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Extract username from token payload
        username = payload.get("uid")
        if not username:
            raise HTTPException(
                status_code=401,
                detail="Authentication failed: Token is missing a valid user identifier.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Fetch user from the database.+++++
        user_data = db.query(Users).filter(Users.user_name == username).first()
        if not user_data:
            raise HTTPException(
                status_code=401,
                detail=f"Authentication failed: User '{username}' not found in the system.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return user_data
