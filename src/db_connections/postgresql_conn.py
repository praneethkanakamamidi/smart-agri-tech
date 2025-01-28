import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from fastapi import HTTPException, status


# Load environment variables from a .env file
load_dotenv()

# Retrieve environment variables with fallback defaults to avoid runtime errors
DB_USER = os.getenv("POSTGRES_USER")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")
DB_HOST = os.getenv("POSTGRES_HOST")
DB_NAME = os.getenv("POSTGRES_DB")
DB_PORT = int(os.getenv("POSTGRES_DB_INTERNAL_PORT"))

# Construct the database URL with explicit port support
SQLALCHEMY_DATABASE_URL = (
    f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# Create the database engine with additional settings for better reliability
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_size=10,  # Define a connection pool size
    max_overflow=20,  # Define how many connections can exceed the pool size
    pool_timeout=30,  # Define timeout for pool connections
    echo=True,  # Disable SQL logging in production (set True for debugging)
    future=True,  # Use SQLAlchemy 2.0 style features for forward compatibility
)

# Configure the session factory with additional options for improved safety
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,  # Prevent objects from being expired after commit
)

# Define the declarative base
Base = declarative_base()

# Dependency to get a database session
def get_db():
    """
    Dependency to get a database session.
    Ensures the session is properly closed after use.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during the database operation: {str(e)}",
            headers={"Content-Type": "application/json"}
        )
    finally:
        db.close()
