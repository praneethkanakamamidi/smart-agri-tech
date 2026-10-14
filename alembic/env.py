from logging.config import fileConfig
import os
import sys

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

# Import Base and all models so metadata is populated for autogenerate
# Use sync URL for migrations (Alembic requires sync engine)
from src.db_connections.database import Base, SQLALCHEMY_DATABASE_URL
import src.data_models.registry  # noqa: F401  (registers every model on Base.metadata)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Override sqlalchemy.url with project's database URL from env
config.set_main_option("sqlalchemy.url", SQLALCHEMY_DATABASE_URL)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Expression indexes created with raw SQL in migrations (PostGIS geography points, full-text
# search). Autogenerate can't round-trip their expressions, so the drift check skips them.
UNMANAGED_INDEXES = {
    "idx_farmer_profiles_geo", "idx_vendor_profiles_geo", "idx_listing_pickup_geo", "idx_listing_embeddings_fts",
}
# PostGIS creates this table in the public schema; it is not ours to manage.
UNMANAGED_TABLES = {"spatial_ref_sys"}


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "index" and (name in UNMANAGED_INDEXES or (name or "").startswith("idx_listing_emb_ann_")):
        return False
    if type_ == "table" and name in UNMANAGED_TABLES:
        return False
    return True


def compare_type(context, inspected_column, metadata_column, inspected_type, metadata_type):
    # pgvector columns are dimension-free by design (one row per embedding model version).
    if type(metadata_type).__name__ in ("VECTOR", "Vector"):
        return False
    return None  # default comparison for everything else


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=compare_type,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=compare_type,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
