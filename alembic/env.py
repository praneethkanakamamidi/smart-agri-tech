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
from src.db_connections.postgresql_conn import Base, SQLALCHEMY_DATABASE_URL
from src.data_models.users_model import Users
from src.data_models.roles_model import Roles
from src.data_models.permissions_model import Permissions
from src.data_models.role_permissions import RolePermissions
from src.data_models.miscellaneous_model import Miscellaneous_Data
from src.data_models.crops_model import Crops
from src.data_models.soil_model import Soil
from src.data_models.fertilizers_model import Fertilizers
from src.data_models.farmer_inventory_model import FarmerInventory
from src.data_models.states_model import States
from src.data_models.districts_model import Districts
from src.data_models.orders_model import Orders
from src.data_models.transactions_model import Transactions
from src.data_models.market_offers_model import MarketOffers

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Override sqlalchemy.url with project's database URL from env
config.set_main_option("sqlalchemy.url", SQLALCHEMY_DATABASE_URL)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


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
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
