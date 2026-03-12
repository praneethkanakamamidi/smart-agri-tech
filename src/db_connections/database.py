"""
Database layer with clear separation between synchronous and asynchronous access.

- sync_engine / SyncSessionLocal: For migrations, scripts, background jobs
- async_engine / AsyncSessionLocal: For API endpoints (non-blocking I/O)
"""
import os
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncGenerator, Generator

from dotenv import load_dotenv
from fastapi import HTTPException, status
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()

DB_USER = os.getenv("POSTGRES_USER")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")
DB_HOST = os.getenv("POSTGRES_HOST")
DB_NAME = os.getenv("POSTGRES_DB")
DB_PORT = int(os.getenv("POSTGRES_DB_INTERNAL_PORT", "5432"))

# Sync: postgresql+psycopg2 (blocking driver)
SQLALCHEMY_DATABASE_URL = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# Async: postgresql+asyncpg (non-blocking driver)
SQLALCHEMY_DATABASE_URL_ASYNC = (
    f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# ---------------------------------------------------------------------------
# Synchronous engine and session (migrations, scripts, sync components)
# ---------------------------------------------------------------------------
sync_engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    echo=False,
    future=True,
)

SyncSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=sync_engine,
    expire_on_commit=False,
)

# ---------------------------------------------------------------------------
# Asynchronous engine and session (API endpoints)
# ---------------------------------------------------------------------------
async_engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL_ASYNC,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

# ---------------------------------------------------------------------------
# Declarative base (shared)
# ---------------------------------------------------------------------------
Base = declarative_base()


# ---------------------------------------------------------------------------
# Dependency providers
# ---------------------------------------------------------------------------
def get_db_sync() -> Generator[Session, None, None]:
    """Synchronous session for migrations, scripts, background jobs."""
    db = SyncSessionLocal()
    try:
        yield db
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )
    finally:
        db.close()


async def get_db_async() -> AsyncGenerator[AsyncSession, None]:
    """Asynchronous session for API endpoints."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )
