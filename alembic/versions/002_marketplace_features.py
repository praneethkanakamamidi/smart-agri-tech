"""marketplace features: notifications, inbox, reviews, buy requests,
favourites, crop alerts, farm expenses, disputes, listing lifecycle

Revision ID: 002
Revises: 001
Create Date: 2026-10-13

"""
from alembic import op
import sqlalchemy as sa

from src.db_connections.migration_helpers import add_column, has_table


# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def _create_table(name, *args, **kwargs):
    if not has_table(name):
        op.create_table(name, *args, **kwargs)
        return True
    return False


def _create_index(name, table, cols):
    op.execute(f'CREATE INDEX IF NOT EXISTS {name} ON {table} ({", ".join(cols)})')


def upgrade() -> None:
    # --- Listing lifecycle on farmer_inventory ---
    add_column('farmer_inventory', sa.Column('quality_grade', sa.String(length=10), nullable=True))
    add_column('farmer_inventory', sa.Column('harvest_date', sa.Date(), nullable=True))
    add_column('farmer_inventory', sa.Column('available_until', sa.Date(), nullable=True))

    # --- Notifications ---
    _create_table(
        'notifications',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('type', sa.String(length=40), nullable=False),
        sa.Column('title', sa.String(length=120), nullable=False),
        sa.Column('message', sa.String(length=500), nullable=True),
        sa.Column('ref_type', sa.String(length=40), nullable=True),
        sa.Column('ref_id', sa.Integer(), nullable=True),
        sa.Column('is_read', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    _create_index('idx_notifications_user_read', 'notifications', ['user_id', 'is_read'])

    # --- Inbox messages ---
    _create_table(
        'messages',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('sender', sa.Integer(), nullable=False),
        sa.Column('receiver', sa.Integer(), nullable=False),
        sa.Column('offer_id', sa.Integer(), nullable=True),
        sa.Column('order_id', sa.Integer(), nullable=True),
        sa.Column('body', sa.String(length=1000), nullable=False),
        sa.Column('is_read', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['sender'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['receiver'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['offer_id'], ['market_offers.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    _create_index('idx_messages_sender', 'messages', ['sender'])
    _create_index('idx_messages_receiver_read', 'messages', ['receiver', 'is_read'])

    # --- Reviews ---
    _create_table(
        'reviews',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('reviewer', sa.Integer(), nullable=False),
        sa.Column('reviewee', sa.Integer(), nullable=False),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('comment', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reviewer'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reviewee'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('order_id', 'reviewer', name='uq_reviews_order_reviewer'),
        sa.CheckConstraint('rating BETWEEN 1 AND 5', name='ck_reviews_rating'),
    )
    _create_index('idx_reviews_reviewee', 'reviews', ['reviewee'])

    # --- Buy requests ---
    _create_table(
        'buy_requests',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('vendor', sa.Integer(), nullable=False),
        sa.Column('crop', sa.Integer(), nullable=False),
        sa.Column('quantity_kg', sa.Float(), nullable=False),
        sa.Column('max_price_per_kg', sa.Float(), nullable=True),
        sa.Column('state', sa.Integer(), nullable=True),
        sa.Column('district', sa.Integer(), nullable=True),
        sa.Column('needed_by', sa.Date(), nullable=True),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['vendor'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['crop'], ['crops.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['state'], ['states.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['district'], ['districts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    _create_index('idx_buy_requests_status_crop', 'buy_requests', ['status', 'crop'])
    _create_index('idx_buy_requests_vendor', 'buy_requests', ['vendor'])

    _create_table(
        'buy_request_responses',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('buy_request_id', sa.Integer(), nullable=False),
        sa.Column('farmer', sa.Integer(), nullable=False),
        sa.Column('farmer_inventory', sa.Integer(), nullable=False),
        sa.Column('price_per_kg', sa.Float(), nullable=False),
        sa.Column('quantity_kg', sa.Float(), nullable=False),
        sa.Column('message', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['buy_request_id'], ['buy_requests.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['farmer'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['farmer_inventory'], ['farmer_inventory.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    _create_index('idx_buy_request_responses_request', 'buy_request_responses', ['buy_request_id'])
    _create_index('idx_buy_request_responses_farmer', 'buy_request_responses', ['farmer'])

    # --- Favourite farmers ---
    _create_table(
        'favourite_farmers',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('vendor', sa.Integer(), nullable=False),
        sa.Column('farmer', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['vendor'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['farmer'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('vendor', 'farmer', name='uq_favourite_farmers_vendor_farmer'),
    )
    _create_index('idx_favourite_farmers_farmer', 'favourite_farmers', ['farmer'])

    # --- Crop alerts ---
    _create_table(
        'crop_alerts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('vendor', sa.Integer(), nullable=False),
        sa.Column('crop', sa.Integer(), nullable=False),
        sa.Column('state', sa.Integer(), nullable=True),
        sa.Column('district', sa.Integer(), nullable=True),
        sa.Column('min_quantity_kg', sa.Float(), nullable=True),
        sa.Column('max_price_per_kg', sa.Float(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['vendor'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['crop'], ['crops.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['state'], ['states.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['district'], ['districts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    _create_index('idx_crop_alerts_crop_active', 'crop_alerts', ['crop', 'is_active'])

    # --- Farm expenses ---
    _create_table(
        'farm_expenses',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('farmer', sa.Integer(), nullable=False),
        sa.Column('crop', sa.Integer(), nullable=True),
        sa.Column('category', sa.String(length=30), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('expense_date', sa.Date(), nullable=False),
        sa.Column('note', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['farmer'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['crop'], ['crops.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    _create_index('idx_farm_expenses_farmer_date', 'farm_expenses', ['farmer', 'expense_date'])

    # --- Disputes ---
    _create_table(
        'disputes',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('raised_by', sa.Integer(), nullable=False),
        sa.Column('against', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(length=40), nullable=False),
        sa.Column('description', sa.String(length=1000), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('resolution', sa.String(length=1000), nullable=True),
        sa.Column('resolved_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['raised_by'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['against'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['resolved_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    _create_index('idx_disputes_status', 'disputes', ['status'])
    # Lookup values and roles are reference data: python -m src.seeds


def downgrade() -> None:
    op.drop_index('idx_disputes_status', table_name='disputes')
    op.drop_table('disputes')
    op.drop_index('idx_farm_expenses_farmer_date', table_name='farm_expenses')
    op.drop_table('farm_expenses')
    op.drop_index('idx_crop_alerts_crop_active', table_name='crop_alerts')
    op.drop_table('crop_alerts')
    op.drop_index('idx_favourite_farmers_farmer', table_name='favourite_farmers')
    op.drop_table('favourite_farmers')
    op.drop_index('idx_buy_request_responses_farmer', table_name='buy_request_responses')
    op.drop_index('idx_buy_request_responses_request', table_name='buy_request_responses')
    op.drop_table('buy_request_responses')
    op.drop_index('idx_buy_requests_vendor', table_name='buy_requests')
    op.drop_index('idx_buy_requests_status_crop', table_name='buy_requests')
    op.drop_table('buy_requests')
    op.drop_index('idx_reviews_reviewee', table_name='reviews')
    op.drop_table('reviews')
    op.drop_index('idx_messages_receiver_read', table_name='messages')
    op.drop_index('idx_messages_sender', table_name='messages')
    op.drop_table('messages')
    op.drop_index('idx_notifications_user_read', table_name='notifications')
    op.drop_table('notifications')
    op.drop_column('farmer_inventory', 'available_until')
    op.drop_column('farmer_inventory', 'harvest_date')
    op.drop_column('farmer_inventory', 'quality_grade')
    # Seeded lookup rows (order statuses, admin role) are left in place: orders/users may reference them.
