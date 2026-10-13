"""
Fixtures for seeding tests.

Database tests need a PostgreSQL database the tests may write to:
    TEST_DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/smart_agri_tech_test
Each test runs in its own temporary schema, which is dropped afterwards.
"""
import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import src.data_models.registry  # noqa: F401
from src.db_connections.database import Base

ROOT = Path(__file__).resolve().parents[2]
TABLES = ("miscellaneous_data", "roles", "states", "districts", "users", "audit_logs")


def _migration_004():
    spec = importlib.util.spec_from_file_location(
        "migration_004", ROOT / "alembic" / "versions" / "004_reference_data_uniqueness.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def database_url():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set; skipping PostgreSQL seeding tests.")
    return url


def _make_schema(database_url, with_unique_indexes: bool):
    schema = f"seed_test_{uuid.uuid4().hex[:10]}"
    admin = create_engine(database_url, poolclass=NullPool)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(database_url, poolclass=NullPool, connect_args={"options": f"-csearch_path={schema}"})
    # The models declare the same unique indexes migration 004 creates.
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[t] for t in TABLES])
    if not with_unique_indexes:
        with engine.begin() as conn:
            for _, _, index_name in _migration_004().REFERENCE_TABLES:
                conn.execute(text(f'DROP INDEX IF EXISTS "{index_name}"'))
            conn.execute(text("ALTER TABLE states DROP CONSTRAINT IF EXISTS states_state_name_key"))
    return admin, engine, schema


def _drop_schema(admin, engine, schema):
    engine.dispose()
    with admin.begin() as conn:
        conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


@pytest.fixture
def engine(database_url):
    """Schema shaped like production after `alembic upgrade head` (including uniqueness indexes)."""
    admin, engine, schema = _make_schema(database_url, with_unique_indexes=True)
    yield engine
    _drop_schema(admin, engine, schema)


@pytest.fixture
def engine_without_indexes(database_url):
    """Schema as an old database looks before migration 004 (duplicates possible)."""
    admin, engine, schema = _make_schema(database_url, with_unique_indexes=False)
    yield engine
    _drop_schema(admin, engine, schema)


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine, future=True)
