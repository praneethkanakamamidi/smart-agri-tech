"""
PostgreSQL connection module.

Re-exports from database.py for backward compatibility.
API endpoints should use get_db_async from database.py.
Sync components (migrations, scripts) use get_db_sync.
"""
from src.db_connections.database import (
    Base,
    SQLALCHEMY_DATABASE_URL,
    SyncSessionLocal as SessionLocal,
    sync_engine as engine,
    get_db_sync as get_db,
)

__all__ = [
    "Base",
    "SQLALCHEMY_DATABASE_URL",
    "SessionLocal",
    "engine",
    "get_db",
]
