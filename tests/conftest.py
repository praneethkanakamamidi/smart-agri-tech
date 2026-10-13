"""
Test-session setup.

When TEST_DATABASE_URL is set (a PostgreSQL server the tests may write to), a throwaway
database is created for the session, brought to `alembic upgrade head`, seeded with
`python -m src.seeds`, and the application is pointed at it. It is dropped afterwards.
Without TEST_DATABASE_URL, database tests are skipped.

This must run before any `src.*` module is imported, because the engines are built from the
POSTGRES_* environment variables at import time.
"""
import os
import tempfile
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

E2E_DB = {"name": None, "admin_url": None}

# Deterministic, isolated settings for every test run.
os.environ.update({
    "RATE_LIMIT_ENABLED": "false",
    "SCHEDULER_ENABLED": "false",
    "OTP_STORE": "postgres",
    "OTP_DEBUG_ECHO": "true",
    "EMAIL_PROVIDER": "log",
    "SMS_PROVIDER": "log",
    "PUSH_PROVIDER": "log",
    "UPLOAD_DIR": os.path.join(tempfile.gettempdir(), "smart-agri-tech-test-uploads"),
    "ADMIN_MFA_REQUIRED": "false",
})
os.environ.setdefault("ACCESS_TOKEN", "test-access-secret-" + uuid.uuid4().hex)
os.environ.setdefault("REFRESH_TOKEN", "test-refresh-secret-" + uuid.uuid4().hex)
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("DATA_ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktMzItYnl0ZXMta2V5LTAwMDA=")


def pytest_configure(config):
    base_url = os.getenv("TEST_DATABASE_URL")
    if not base_url:
        return
    url = make_url(base_url)
    name = f"e2e_{uuid.uuid4().hex[:10]}"
    admin = create_engine(base_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    E2E_DB.update(name=name, admin_url=base_url)
    os.environ.update({
        "POSTGRES_USER": url.username or "",
        "POSTGRES_PASSWORD": url.password or "",
        "POSTGRES_HOST": url.host or "localhost",
        "POSTGRES_DB_INTERNAL_PORT": str(url.port or 5432),
        "POSTGRES_DB": name,
    })

    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic.ini")), "head")

    from src.seeds.__main__ import main as seed

    assert seed([]) == 0, "seeding the e2e database failed"


def pytest_unconfigure(config):
    if not E2E_DB["name"]:
        return
    try:
        from src.db_connections.database import sync_engine

        sync_engine.dispose()
    except Exception:
        pass
    admin = create_engine(E2E_DB["admin_url"], poolclass=NullPool, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{E2E_DB["name"]}" WITH (FORCE)'))
    admin.dispose()
