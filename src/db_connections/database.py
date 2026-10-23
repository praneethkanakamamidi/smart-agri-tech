"""
Database layer with clear separation between synchronous and asynchronous access.

- sync_engine / SyncSessionLocal: For migrations, scripts, background jobs
- async_engine / AsyncSessionLocal: For API endpoints (non-blocking I/O)

Pool sizing and timeouts are configurable through DB_* environment variables.
"""
import json
import os
import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import AsyncGenerator, Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

load_dotenv()

DB_USER = os.getenv("POSTGRES_USER")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")
DB_HOST = os.getenv("POSTGRES_HOST")
DB_NAME = os.getenv("POSTGRES_DB")
DB_PORT = int(os.getenv("POSTGRES_DB_INTERNAL_PORT", "5432"))

POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))
POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "1800"))  # recycle before typical LB/firewall idle cut-offs
STATEMENT_TIMEOUT_MS = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "30000"))  # 0 disables

# Sync: postgresql+psycopg2 (blocking driver)
SQLALCHEMY_DATABASE_URL = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# Async: postgresql+asyncpg (non-blocking driver)
SQLALCHEMY_DATABASE_URL_ASYNC = (
    f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)


def _json_default(value):
    """Types that reach JSON columns from service results: money stays exact (as a string, the way
    the API returns it), dates become ISO-8601."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def json_serializer(value) -> str:
    return json.dumps(value, default=_json_default)

# ---------------------------------------------------------------------------
# Synchronous engine and session (migrations, scripts, sync components)
# ---------------------------------------------------------------------------
sync_engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_timeout=POOL_TIMEOUT,
    pool_recycle=POOL_RECYCLE,
    pool_pre_ping=True,
    echo=False,
    future=True,
    json_serializer=json_serializer,
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
_async_connect_args = {"server_settings": {"application_name": "smart-agri-tech-api"}}
if STATEMENT_TIMEOUT_MS > 0:
    _async_connect_args["server_settings"]["statement_timeout"] = str(STATEMENT_TIMEOUT_MS)

async_engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL_ASYNC,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_timeout=POOL_TIMEOUT,
    pool_recycle=POOL_RECYCLE,
    pool_pre_ping=True,
    echo=False,
    connect_args=_async_connect_args,
    json_serializer=json_serializer,
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
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def get_db_async() -> AsyncGenerator[AsyncSession, None]:
    """
    Asynchronous session for API endpoints.

    Any exception raised by the endpoint (including HTTPException) is re-raised unchanged
    after rolling back, so a 404/409 stays a 404/409 and unexpected errors reach the global
    error handler. Never wrap them here.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose_engines():
    """Close pooled connections on shutdown."""
    await async_engine.dispose()
    sync_engine.dispose()
