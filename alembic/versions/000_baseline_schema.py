"""baseline: the original schema, for fresh databases

Databases created earlier from the original SQL schema scripts already have these tables; every
statement is CREATE ... IF NOT EXISTS, so running this on them is a no-op. Reference data is
not part of migrations; see docs/seeding.md.

Revision ID: 000
Revises:
Create Date: 2026-10-13

"""
from alembic import op

revision = '000'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS miscellaneous_data (
        id SERIAL PRIMARY KEY,
        category VARCHAR(50),
        value VARCHAR(150),
        created_by INTEGER,
        updated_by INTEGER,
        created_at TIMESTAMP,
        updated_at TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS states (
        id SERIAL PRIMARY KEY,
        state_name VARCHAR(100) UNIQUE NOT NULL,
        created_by INTEGER,
        created_at TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS districts (
        id SERIAL PRIMARY KEY,
        district_name VARCHAR(100) NOT NULL,
        state_id INTEGER REFERENCES states(id) ON DELETE CASCADE,
        created_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS roles (
        id SERIAL PRIMARY KEY,
        name VARCHAR(30),
        status INTEGER REFERENCES miscellaneous_data(id) ON DELETE CASCADE,
        created_time TIMESTAMP,
        updated_time TIMESTAMP,
        created_by INTEGER,
        updated_by INTEGER
    );
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        user_name VARCHAR(50),
        first_name VARCHAR(30),
        last_name VARCHAR(30),
        password VARCHAR(150),
        status INTEGER REFERENCES miscellaneous_data(id) ON DELETE CASCADE,
        state INTEGER REFERENCES states(id) ON DELETE CASCADE,
        district INTEGER REFERENCES districts(id) ON DELETE CASCADE,
        role_id INTEGER REFERENCES roles(id) ON DELETE CASCADE,
        created_time TIMESTAMP,
        updated_time TIMESTAMP,
        updated_by INTEGER REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS permissions (
        id SERIAL PRIMARY KEY,
        permission_name VARCHAR(30),
        permission_key VARCHAR(50),
        created_time TIMESTAMP,
        updated_time TIMESTAMP,
        created_by INTEGER REFERENCES users(id) ON DELETE CASCADE,
        updated_by INTEGER REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS role_permissions (
        id SERIAL PRIMARY KEY,
        role_id INTEGER REFERENCES roles(id) ON DELETE CASCADE,
        permission_id INTEGER REFERENCES permissions(id) ON DELETE CASCADE,
        can_read INTEGER REFERENCES miscellaneous_data(id) ON DELETE CASCADE,
        can_write INTEGER REFERENCES miscellaneous_data(id) ON DELETE CASCADE,
        can_delete INTEGER REFERENCES miscellaneous_data(id) ON DELETE CASCADE,
        created_time TIMESTAMP,
        updated_time TIMESTAMP,
        created_by INTEGER REFERENCES users(id) ON DELETE CASCADE,
        updated_by INTEGER REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS crops (
        id SERIAL PRIMARY KEY,
        crop_name VARCHAR(10),
        crop_type VARCHAR(10),
        description VARCHAR(150),
        status INTEGER REFERENCES miscellaneous_data(id) ON DELETE CASCADE,
        created_by INTEGER REFERENCES users(id) ON DELETE CASCADE,
        updated_by INTEGER REFERENCES users(id) ON DELETE CASCADE,
        created_at TIMESTAMP,
        updated_at TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS soil (
        id SERIAL PRIMARY KEY,
        soil_name VARCHAR(10),
        soil_texture VARCHAR(10),
        description VARCHAR(150),
        status INTEGER REFERENCES miscellaneous_data(id) ON DELETE CASCADE,
        created_by INTEGER REFERENCES users(id) ON DELETE CASCADE,
        updated_by INTEGER REFERENCES users(id) ON DELETE CASCADE,
        created_at TIMESTAMP,
        updated_at TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS fertilizers (
        id SERIAL PRIMARY KEY,
        fertilizer_name VARCHAR(10),
        application_method VARCHAR(10),
        description VARCHAR(150),
        status INTEGER REFERENCES miscellaneous_data(id) ON DELETE CASCADE,
        created_by INTEGER REFERENCES users(id) ON DELETE CASCADE,
        updated_by INTEGER REFERENCES users(id) ON DELETE CASCADE,
        created_at TIMESTAMP,
        updated_at TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS farmer_inventory (
        id SERIAL PRIMARY KEY,
        crop INTEGER REFERENCES crops(id) ON DELETE CASCADE,
        fertilizer INTEGER REFERENCES fertilizers(id) ON DELETE SET NULL,
        soil INTEGER REFERENCES soil(id) ON DELETE SET NULL,
        weight_kg INTEGER,
        proposed_cost INTEGER,
        description VARCHAR(150),
        created_by INTEGER REFERENCES users(id) ON DELETE CASCADE,
        updated_by INTEGER REFERENCES users(id) ON DELETE CASCADE,
        created_at TIMESTAMP,
        updated_at TIMESTAMP
    );
    ALTER TABLE farmer_inventory ADD COLUMN IF NOT EXISTS description VARCHAR(150);
    CREATE TABLE IF NOT EXISTS orders (
        id SERIAL PRIMARY KEY,
        farmer_inventory INTEGER REFERENCES farmer_inventory(id) ON DELETE CASCADE,
        vendor INTEGER REFERENCES users(id) ON DELETE CASCADE,
        farmer INTEGER REFERENCES users(id) ON DELETE CASCADE,
        quantity_kg DOUBLE PRECISION,
        total_price INTEGER,
        status INTEGER REFERENCES miscellaneous_data(id) ON DELETE CASCADE,
        created_at TIMESTAMP,
        updated_at TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS transactions (
        id SERIAL PRIMARY KEY,
        order_id INTEGER REFERENCES orders(id) ON DELETE CASCADE,
        razorpay_order_id VARCHAR NOT NULL UNIQUE,
        razorpay_payment_id VARCHAR UNIQUE,
        razorpay_signature VARCHAR,
        amount_paid INTEGER NOT NULL,
        currency VARCHAR,
        status INTEGER REFERENCES miscellaneous_data(id) ON DELETE CASCADE,
        created_at TIMESTAMP
    );
    """)
    # Reference data (lookup values, roles, states, districts) is seeded separately: python -m src.seeds


def downgrade() -> None:
    # The baseline is never dropped automatically: it may hold data created before migrations existed.
    pass
