"""add market_offers table

Revision ID: 001
Revises:
Create Date: 2025-03-11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'market_offers',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('farmer_inventory', sa.Integer(), nullable=False),
        sa.Column('vendor', sa.Integer(), nullable=False),
        sa.Column('farmer', sa.Integer(), nullable=False),
        sa.Column('vendor_offer_price', sa.Float(), nullable=False),
        sa.Column('farmer_counter_price', sa.Float(), nullable=True),
        sa.Column('quantity_kg', sa.Float(), nullable=False),
        sa.Column('message', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['farmer_inventory'], ['farmer_inventory.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['vendor'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['farmer'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_market_offers_farmer', 'market_offers', ['farmer'], unique=False)
    op.create_index('idx_market_offers_vendor', 'market_offers', ['vendor'], unique=False)
    op.create_index('idx_market_offers_inventory', 'market_offers', ['farmer_inventory'], unique=False)
    op.create_index('idx_market_offers_status', 'market_offers', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_market_offers_status', table_name='market_offers')
    op.drop_index('idx_market_offers_inventory', table_name='market_offers')
    op.drop_index('idx_market_offers_vendor', table_name='market_offers')
    op.drop_index('idx_market_offers_farmer', table_name='market_offers')
    op.drop_table('market_offers')
