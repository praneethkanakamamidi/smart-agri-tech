"""query indexes: cover foreign keys, list/sort paths and background-job scans

PostgreSQL does not index foreign-key columns on its own. Without these, per-user lists
(orders, negotiations, chat, tickets) and the scheduler's sweeps (offer expiry, confirmation
timeouts, notification retries, recurring orders, account deletion) scan whole tables, and
deleting or SET NULL-ing a parent row scans every child table.

Partial indexes match the predicates the code uses (e.g. pending offers by expiry, the public
marketplace feed), so they stay small. Three single-column indexes are replaced by composites
that serve the same lookups plus the ORDER BY:
    idx_orders_farmer   -> idx_orders_farmer_created
    idx_orders_vendor   -> idx_orders_vendor_created
    idx_messages_sender -> idx_messages_conversation

Indexes are built with CREATE INDEX CONCURRENTLY so a deploy does not block writes. That
cannot run inside a transaction, so this revision runs in an autocommit block. If a build is
interrupted, PostgreSQL leaves an INVALID index behind; re-running the upgrade drops and
rebuilds it.

Revision ID: 005
Revises: 004
Create Date: 2026-10-13

"""
from alembic import op
import sqlalchemy as sa

revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None

# (index name, table, column list, partial-index predicate or None)
INDEXES = (
    # users: login / token resolution, admin filters, location filters, deletion sweep
    ("idx_users_user_name", "users", "user_name", None),
    ("idx_users_role", "users", "role_id", None),
    ("idx_users_location", "users", "state, district", None),
    ("idx_users_pending_deletion", "users", "deletion_requested_at",
     "deletion_requested_at IS NOT NULL AND deleted_at IS NULL"),

    # listings: public feed, crop filters, expiry sweep, reference-data FKs
    ("idx_listing_crop", "farmer_inventory", "crop", None),
    ("idx_listing_feed_recent", "farmer_inventory", "created_at DESC NULLS LAST, id DESC",
     "status = 'active' AND deleted_at IS NULL"),
    ("idx_listing_available_until", "farmer_inventory", "available_until", "available_until IS NOT NULL"),
    ("idx_listing_soil", "farmer_inventory", "soil", "soil IS NOT NULL"),
    ("idx_listing_fertilizer", "farmer_inventory", "fertilizer", "fertilizer IS NOT NULL"),
    ("idx_listing_images_listing", "listing_images", "listing_id, sort_order", None),
    ("idx_listing_images_file", "listing_images", "file_id", None),
    ("idx_listing_certifications_listing", "listing_certifications", "listing_id", None),
    ("idx_listing_certifications_status", "listing_certifications", "status, created_at", None),
    ("idx_listing_certifications_file", "listing_certifications", "file_id", "file_id IS NOT NULL"),
    ("idx_saved_listings_listing", "saved_listings", "listing_id", None),
    ("idx_inventory_movements_listing", "inventory_movements", "listing_id, created_at", None),
    ("idx_inventory_reservations_order", "inventory_reservations", "order_id, status", None),
    ("idx_inventory_reservations_listing", "inventory_reservations", "listing_id", None),
    ("idx_harvest_plans_farmer_date", "harvest_plans", "farmer, expected_harvest_date", None),
    ("idx_harvest_plans_listing", "harvest_plans", "listing_id", "listing_id IS NOT NULL"),
    ("idx_crops_category", "crops", "category_id", None),

    # negotiations and offers
    ("idx_negotiations_vendor_updated", "negotiations", "vendor, updated_at", None),
    ("idx_negotiations_farmer_updated", "negotiations", "farmer, updated_at", None),
    ("idx_negotiations_listing", "negotiations", "listing_id, vendor, status", None),
    ("idx_negotiations_order", "negotiations", "order_id", "order_id IS NOT NULL"),
    ("idx_negotiations_created", "negotiations", "created_at", None),
    ("idx_offers_pending_expiry", "offers", "expires_at", "status = 'PENDING'"),
    ("idx_offers_recipient", "offers", "recipient", None),
    ("idx_offers_offered_by", "offers", "offered_by", None),
    ("idx_offers_supersedes", "offers", "supersedes_offer_id", "supersedes_offer_id IS NOT NULL"),

    # orders and their children
    ("idx_orders_farmer_created", "orders", "farmer, created_at", None),
    ("idx_orders_vendor_created", "orders", "vendor, created_at", None),
    ("idx_orders_status_created", "orders", "status, created_at", None),
    ("idx_orders_created", "orders", "created_at", None),
    ("idx_orders_listing", "orders", "farmer_inventory", None),
    ("idx_orders_negotiation", "orders", "negotiation_id", "negotiation_id IS NOT NULL"),
    ("idx_orders_offer", "orders", "offer_id", "offer_id IS NOT NULL"),
    ("idx_order_status_history_order", "order_status_history", "order_id", None),
    ("idx_order_adjustments_order", "order_adjustments", "order_id", None),
    ("idx_invoices_order", "invoices", "order_id", None),
    ("idx_invoices_transaction", "invoices", "transaction_id", "transaction_id IS NOT NULL"),

    # payments
    ("idx_transactions_order_status", "transactions", "order_id, status", None),
    ("idx_transactions_status_created", "transactions", "status, created_at", None),
    ("idx_refunds_order_status", "refunds", "order_id, status", None),
    ("idx_refunds_status_created", "refunds", "status, created_at", None),
    ("idx_refunds_gateway_id", "refunds", "gateway_refund_id", "gateway_refund_id IS NOT NULL"),
    ("idx_refunds_transaction", "refunds", "transaction_id", "transaction_id IS NOT NULL"),
    ("idx_refunds_dispute", "refunds", "dispute_id", "dispute_id IS NOT NULL"),
    ("idx_settlements_farmer_created", "settlements", "farmer, created_at", None),
    ("idx_settlements_status_created", "settlements", "status, created_at", None),

    # disputes, reviews
    ("idx_disputes_order", "disputes", "order_id, status", None),
    ("idx_disputes_raised_by", "disputes", "raised_by", None),
    ("idx_disputes_against", "disputes", "against", None),
    ("idx_disputes_assigned", "disputes", "assigned_to", "assigned_to IS NOT NULL"),
    ("idx_disputes_created", "disputes", "created_at", None),
    ("idx_dispute_messages_dispute", "dispute_messages", "dispute_id", None),
    ("idx_reviews_reviewer", "reviews", "reviewer", None),

    # chat: conversation threads plus the optional context FKs (SET NULL on parent delete)
    ("idx_messages_conversation", "messages", "sender, receiver, created_at", None),
    ("idx_messages_order", "messages", "order_id", "order_id IS NOT NULL"),
    ("idx_messages_listing", "messages", "listing_id", "listing_id IS NOT NULL"),
    ("idx_messages_negotiation", "messages", "negotiation_id", "negotiation_id IS NOT NULL"),
    ("idx_messages_dispute", "messages", "dispute_id", "dispute_id IS NOT NULL"),
    ("idx_messages_attachment", "messages", "attachment_file_id", "attachment_file_id IS NOT NULL"),
    ("idx_messages_offer", "messages", "offer_id", "offer_id IS NOT NULL"),

    # procurement
    ("idx_buy_request_responses_listing", "buy_request_responses", "farmer_inventory", None),
    ("idx_buy_request_responses_negotiation", "buy_request_responses", "negotiation_id",
     "negotiation_id IS NOT NULL"),
    ("idx_buy_request_responses_order", "buy_request_responses", "order_id", "order_id IS NOT NULL"),
    ("idx_buy_request_invites_farmer", "buy_request_invites", "farmer", None),
    ("idx_crop_alerts_vendor", "crop_alerts", "vendor", None),
    ("idx_recurring_orders_due", "recurring_orders", "next_run_date", "status = 'active'"),
    ("idx_recurring_orders_vendor", "recurring_orders", "vendor", None),
    ("idx_recurring_orders_farmer", "recurring_orders", "farmer", None),
    ("idx_recurring_orders_listing", "recurring_orders", "listing_id", None),

    # notifications, sessions, files
    ("idx_notification_deliveries_due", "notification_deliveries", "next_attempt_at", "status = 'pending'"),
    ("idx_notification_deliveries_notification", "notification_deliveries", "notification_id", None),
    ("idx_user_sessions_user", "user_sessions", "user_id", None),
    ("idx_device_tokens_user", "device_tokens", "user_id", None),
    ("idx_stored_files_owner", "stored_files", "owner_id", None),

    # trust & safety, admin queues
    ("idx_verification_requests_user", "verification_requests", "user_id, status", None),
    ("idx_verification_requests_status", "verification_requests", "status, submitted_at", None),
    ("idx_account_appeals_user", "account_appeals", "user_id, status", None),
    ("idx_account_appeals_status", "account_appeals", "status, created_at", None),
    ("idx_reports_target", "reports", "target_type, target_id, status", None),
    ("idx_reports_reporter", "reports", "reporter_id", None),
    ("idx_reports_status", "reports", "status, created_at", None),
    ("idx_user_blocks_blocked", "user_blocks", "blocked_id", None),
    ("idx_audit_logs_entity", "audit_logs", "entity_type, entity_id", None),
    ("idx_audit_logs_actor", "audit_logs", "actor_id", None),
    ("idx_audit_logs_created", "audit_logs", "created_at", None),
    ("idx_support_tickets_user", "support_tickets", "user_id, updated_at", None),
    ("idx_support_tickets_status", "support_tickets", "status, updated_at", None),
    ("idx_support_tickets_assigned", "support_tickets", "assigned_to", "assigned_to IS NOT NULL"),
    ("idx_support_tickets_order", "support_tickets", "order_id", "order_id IS NOT NULL"),
    ("idx_support_ticket_messages_ticket", "support_ticket_messages", "ticket_id", None),
    ("idx_platform_settings_history_key", "platform_settings_history", "key, version", None),
    ("idx_role_permissions_role", "role_permissions", "role_id", None),
)

# Superseded by the composites above; restored on downgrade.
REPLACED = (
    ("idx_orders_farmer", "orders", "farmer"),
    ("idx_orders_vendor", "orders", "vendor"),
    ("idx_messages_sender", "messages", "sender"),
)


def _drop_if_invalid(bind, name: str) -> None:
    """Remove the INVALID leftover of an interrupted CONCURRENTLY build so it is rebuilt."""
    invalid = bind.execute(sa.text("""
        SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname = :name AND n.nspname = current_schema() AND NOT i.indisvalid
    """), {"name": name}).first()
    if invalid:
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")


def _create(name: str, table: str, columns: str, where: str | None) -> None:
    sql = f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table} ({columns})"
    op.execute(f"{sql} WHERE {where}" if where else sql)


def upgrade() -> None:
    offline = op.get_context().as_sql  # `alembic upgrade --sql` has no connection to inspect
    with op.get_context().autocommit_block():
        bind = op.get_bind()
        for name, table, columns, where in INDEXES:
            if not offline:
                _drop_if_invalid(bind, name)
            _create(name, table, columns, where)
        for name, _table, _columns in REPLACED:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, table, columns in REPLACED:
            _create(name, table, columns, None)
        for name, _table, _columns, _where in reversed(INDEXES):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
