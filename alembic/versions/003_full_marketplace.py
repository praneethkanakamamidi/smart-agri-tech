"""full marketplace: profiles & verification, catalog, listing lifecycle, versioned negotiations,
order snapshots & lifecycle, inventory reservations, payments/refunds/settlements, logistics,
dispute workflow, chat context, notification channels, admin & platform tables

Revision ID: 003
Revises: 002
Create Date: 2026-10-13

"""
from alembic import op
import sqlalchemy as sa

from src.db_connections.migration_helpers import (
    add_column, drop_column, has_table, insert_if_missing, seed_misc,
)

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None

# Brand-new tables, created from the model definitions (dependency order is resolved by SQLAlchemy).
NEW_TABLES = (
    "produce_categories", "units", "quality_standards", "stored_files", "farmer_profiles", "vendor_profiles",
    "verification_requests", "listing_images", "listing_price_tiers", "listing_certifications", "saved_listings",
    "harvest_plans", "negotiations", "offers", "inventory_reservations", "inventory_movements",
    "order_status_history", "order_adjustments", "invoices", "refunds", "settlements", "webhook_events",
    "shipments", "dispute_messages", "platform_settings", "platform_settings_history", "audit_logs",
    "idempotency_keys", "user_sessions", "device_tokens", "otp_codes", "reports", "user_blocks",
    "account_appeals", "announcements", "support_tickets", "support_ticket_messages",
    "notification_preferences", "notification_deliveries", "recurring_orders", "buy_request_invites",
)

# Legacy order_status value -> new lifecycle value
ORDER_STATUS_MAP = {
    "pending": "pending_confirmation",
    "accepted": "confirmed",
    "rejected": "cancelled",
    "dispatched": "in_transit",
}
NEW_ORDER_STATUSES = (
    "pending_confirmation", "confirmed", "preparing", "ready_for_pickup", "in_transit", "delivered", "completed",
    "cancelled", "delivery_failed", "disputed", "refund_pending", "refunded",
)


def _fk(table, column, ref_table, ondelete="SET NULL"):
    name = f"fk_{table}_{column}"
    op.execute(f"""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{name}') THEN
            ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY ({column}) REFERENCES {ref_table}(id) ON DELETE {ondelete};
        END IF;
    END $$;""")


def upgrade() -> None:
    import src.data_models.registry  # noqa: F401
    from src.db_connections.database import Base

    bind = op.get_bind()

    # ---- widen legacy columns --------------------------------------------------------------
    op.execute("ALTER TABLE miscellaneous_data ALTER COLUMN category TYPE VARCHAR(50)")
    op.execute("ALTER TABLE users ALTER COLUMN user_name TYPE VARCHAR(120)")
    op.execute("ALTER TABLE users ALTER COLUMN password DROP NOT NULL")
    op.execute("ALTER TABLE crops ALTER COLUMN crop_name TYPE VARCHAR(100), ALTER COLUMN crop_type TYPE VARCHAR(50)")
    op.execute("ALTER TABLE soil ALTER COLUMN soil_name TYPE VARCHAR(100), ALTER COLUMN soil_texture TYPE VARCHAR(50)")
    op.execute("ALTER TABLE fertilizers ALTER COLUMN fertilizer_name TYPE VARCHAR(100), "
               "ALTER COLUMN application_method TYPE VARCHAR(50)")

    # ---- lookup rows -------------------------------------------------------------------------
    # Reference data is seeded by `python -m src.seeds`. The only exception: the order-status rows
    # the legacy-order backfill below maps onto must exist before that data migration runs.
    for value in NEW_ORDER_STATUSES:
        seed_misc("order_status", value)

    # ---- new tables --------------------------------------------------------------------------
    tables = [Base.metadata.tables[name] for name in NEW_TABLES]
    Base.metadata.create_all(bind, tables=tables, checkfirst=True)
    op.execute("CREATE SEQUENCE IF NOT EXISTS invoice_number_seq START 1")

    # ---- users -------------------------------------------------------------------------------
    for column in (
        sa.Column("email", sa.String(120)), sa.Column("phone", sa.String(20)),
        sa.Column("email_verified", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("phone_verified", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("preferred_language", sa.String(5), server_default="en", nullable=False),
        sa.Column("verification_status", sa.String(30), server_default="UNVERIFIED", nullable=False),
        sa.Column("suspended_reason", sa.String(255)),
        sa.Column("mfa_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("mfa_secret_encrypted", sa.String(255)),
        sa.Column("last_login_at", sa.DateTime()), sa.Column("deletion_requested_at", sa.DateTime()),
        sa.Column("deleted_at", sa.DateTime()),
    ):
        add_column("users", column)
    # Existing accounts registered with an email and verified it by OTP to become active.
    op.execute("""
        UPDATE users SET email = LOWER(user_name),
               email_verified = COALESCE(status = (SELECT id FROM miscellaneous_data WHERE category='status' AND value='active' LIMIT 1), FALSE)
        WHERE email IS NULL AND user_name LIKE '%@%'
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email ON users (LOWER(email)) WHERE email IS NOT NULL")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_phone ON users (phone) WHERE phone IS NOT NULL")

    # ---- crops (catalog) ------------------------------------------------------------------------
    add_column("crops", sa.Column("category_id", sa.Integer()))
    add_column("crops", sa.Column("name_te", sa.String(100)))
    add_column("crops", sa.Column("default_unit", sa.String(20)))
    _fk("crops", "category_id", "produce_categories")

    # ---- listings ------------------------------------------------------------------------------
    op.execute("ALTER TABLE farmer_inventory ALTER COLUMN weight_kg TYPE NUMERIC(12,2), "
               "ALTER COLUMN proposed_cost TYPE NUMERIC(12,2), ALTER COLUMN description TYPE VARCHAR(500)")
    for column in (
        sa.Column("variety", sa.String(60)), sa.Column("unit", sa.String(20), server_default="kg", nullable=False),
        sa.Column("min_order_qty", sa.Numeric(12, 2)), sa.Column("min_acceptable_price", sa.Numeric(12, 2)),
        sa.Column("packaging", sa.String(30)), sa.Column("availability_date", sa.Date()),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column("reserved_qty", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("sold_qty", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("batch_code", sa.String(40)),
        sa.Column("organic_claim", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("organic_verified", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("delivery_options", sa.String(100), server_default="pickup"),
        sa.Column("views_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("inquiries_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("low_stock_threshold", sa.Numeric(12, 2)), sa.Column("moderation_reason", sa.String(255)),
        sa.Column("deleted_at", sa.DateTime()),
    ):
        add_column("farmer_inventory", column)
    op.execute("UPDATE farmer_inventory SET status = 'expired' WHERE available_until < CURRENT_DATE AND status = 'active'")
    op.execute("CREATE INDEX IF NOT EXISTS idx_listing_market ON farmer_inventory (status, crop) WHERE deleted_at IS NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_listing_farmer ON farmer_inventory (created_by)")

    # ---- orders --------------------------------------------------------------------------------
    op.execute("ALTER TABLE orders ALTER COLUMN quantity_kg TYPE NUMERIC(12,2), ALTER COLUMN total_price TYPE NUMERIC(14,2)")
    for column in (
        sa.Column("order_number", sa.String(30)), sa.Column("unit", sa.String(20), server_default="kg"),
        sa.Column("unit_price", sa.Numeric(12, 2)), sa.Column("subtotal", sa.Numeric(14, 2)),
        sa.Column("packaging_charge", sa.Numeric(12, 2), server_default="0"),
        sa.Column("transport_charge", sa.Numeric(12, 2), server_default="0"),
        sa.Column("platform_fee", sa.Numeric(12, 2), server_default="0"),
        sa.Column("tax_amount", sa.Numeric(12, 2), server_default="0"),
        sa.Column("discount_amount", sa.Numeric(12, 2), server_default="0"),
        sa.Column("payment_terms", sa.String(30)), sa.Column("advance_amount", sa.Numeric(14, 2), server_default="0"),
        sa.Column("fulfillment_mode", sa.String(30)), sa.Column("delivery_instructions", sa.Text()),
        sa.Column("expected_delivery_date", sa.Date()), sa.Column("negotiation_id", sa.Integer()),
        sa.Column("offer_id", sa.Integer()), sa.Column("source", sa.String(30)), sa.Column("terms_snapshot", sa.JSON()),
        sa.Column("agreed_at", sa.DateTime()), sa.Column("farmer_confirmed_at", sa.DateTime()),
        sa.Column("vendor_confirmed_at", sa.DateTime()), sa.Column("confirmation_deadline", sa.DateTime()),
        sa.Column("cancel_reason", sa.String(255)), sa.Column("cancelled_by", sa.Integer()),
        sa.Column("cancelled_at", sa.DateTime()), sa.Column("cancel_requested_by", sa.Integer()),
        sa.Column("cancel_request_reason", sa.String(255)), sa.Column("cancel_requested_at", sa.DateTime()),
        sa.Column("status_before_dispute", sa.String(30)), sa.Column("delivered_at", sa.DateTime()),
        sa.Column("completed_at", sa.DateTime()),
    ):
        add_column("orders", column)
    _fk("orders", "negotiation_id", "negotiations")
    _fk("orders", "offer_id", "offers")
    _fk("orders", "cancelled_by", "users")
    _fk("orders", "cancel_requested_by", "users")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_order_number ON orders (order_number)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_orders_farmer ON orders (farmer)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_orders_vendor ON orders (vendor)")

    # Backfill legacy orders onto the new lifecycle.
    op.execute("""
        UPDATE orders SET
            order_number = COALESCE(order_number, 'ORD-' || TO_CHAR(COALESCE(created_at, NOW()), 'YYYYMMDD') || '-' || LPAD(id::text, 6, '0')),
            unit = COALESCE(unit, 'kg'),
            unit_price = COALESCE(unit_price, ROUND(total_price / NULLIF(quantity_kg, 0), 2)),
            subtotal = COALESCE(subtotal, total_price),
            payment_terms = COALESCE(payment_terms, 'pay_before_dispatch'),
            fulfillment_mode = COALESCE(fulfillment_mode, 'pickup'),
            source = COALESCE(source, 'legacy'),
            agreed_at = COALESCE(agreed_at, created_at),
            vendor_confirmed_at = COALESCE(vendor_confirmed_at, created_at)
    """)
    for old, new in ORDER_STATUS_MAP.items():
        bind.execute(sa.text("""
            UPDATE orders SET status = (SELECT id FROM miscellaneous_data WHERE category='order_status' AND value=:new LIMIT 1)
            WHERE status = (SELECT id FROM miscellaneous_data WHERE category='order_status' AND value=:old LIMIT 1)
        """), {"old": old, "new": new})
    op.execute("""
        UPDATE orders o SET farmer_confirmed_at = COALESCE(o.farmer_confirmed_at, o.created_at)
        FROM miscellaneous_data m
        WHERE o.status = m.id AND m.value NOT IN ('pending_confirmation', 'cancelled')
    """)
    op.execute("""
        UPDATE orders o SET confirmation_deadline = NOW() + INTERVAL '24 hours'
        FROM miscellaneous_data m WHERE o.status = m.id AND m.value = 'pending_confirmation' AND o.confirmation_deadline IS NULL
    """)
    op.execute("""
        UPDATE orders o SET delivered_at = COALESCE(o.delivered_at, o.updated_at, o.created_at)
        FROM miscellaneous_data m WHERE o.status = m.id AND m.value IN ('delivered', 'completed')
    """)
    op.execute("""
        UPDATE orders o SET terms_snapshot = json_build_object(
            'order_number', o.order_number, 'source', 'legacy', 'listing_id', o.farmer_inventory,
            'buyer_id', o.vendor, 'seller_id', o.farmer, 'quantity', o.quantity_kg::text, 'unit', o.unit,
            'unit_price', o.unit_price::text, 'subtotal', o.subtotal::text, 'total_payable', o.total_price::text,
            'platform_fee', '0', 'tax_amount', '0', 'fee_payer', 'vendor', 'payment_terms', o.payment_terms,
            'fulfillment_mode', o.fulfillment_mode,
            'produce', json_build_object('crop_id', fi.crop, 'display_name', c.crop_name, 'quality_grade', fi.quality_grade)
        )
        FROM farmer_inventory fi LEFT JOIN crops c ON c.id = fi.crop
        WHERE fi.id = o.farmer_inventory AND o.terms_snapshot IS NULL
    """)
    # Legacy code subtracted ordered quantity from stock at order time: record it as reserved or sold.
    op.execute("""
        INSERT INTO inventory_reservations (listing_id, order_id, quantity, status, expires_at, reason, created_at)
        SELECT o.farmer_inventory, o.id, o.quantity_kg, 'active',
               CASE WHEN m.value = 'pending_confirmation' THEN o.confirmation_deadline END, 'migrated legacy order', NOW()
        FROM orders o JOIN miscellaneous_data m ON o.status = m.id
        WHERE m.value IN ('pending_confirmation', 'confirmed', 'in_transit')
          AND NOT EXISTS (SELECT 1 FROM inventory_reservations r WHERE r.order_id = o.id)
    """)
    op.execute("""
        UPDATE farmer_inventory fi SET reserved_qty = sub.qty
        FROM (SELECT listing_id, SUM(quantity) qty FROM inventory_reservations WHERE status = 'active' GROUP BY listing_id) sub
        WHERE fi.id = sub.listing_id
    """)
    op.execute("""
        UPDATE farmer_inventory fi SET sold_qty = sub.qty
        FROM (SELECT o.farmer_inventory listing_id, SUM(o.quantity_kg) qty
              FROM orders o JOIN miscellaneous_data m ON o.status = m.id
              WHERE m.value IN ('delivered', 'completed') GROUP BY o.farmer_inventory) sub
        WHERE fi.id = sub.listing_id AND fi.sold_qty = 0
    """)
    op.execute("""
        UPDATE farmer_inventory SET status = CASE WHEN reserved_qty > 0 THEN 'reserved' ELSE 'sold' END
        WHERE status = 'active' AND COALESCE(weight_kg, 0) <= 0
    """)
    op.execute("""
        INSERT INTO shipments (order_id, mode, status, reschedule_count, created_at)
        SELECT o.id, COALESCE(o.fulfillment_mode, 'pickup'), 'planned', 0, NOW() FROM orders o
        WHERE NOT EXISTS (SELECT 1 FROM shipments s WHERE s.order_id = o.id)
    """)

    # ---- transactions ----------------------------------------------------------------------------
    op.execute("ALTER TABLE transactions ALTER COLUMN amount_paid TYPE NUMERIC(14,2), "
               "ALTER COLUMN razorpay_order_id DROP NOT NULL")
    for column in (
        sa.Column("payment_method", sa.String(20), server_default="gateway"),
        sa.Column("purpose", sa.String(20), server_default="full"), sa.Column("reference", sa.String(100)),
        sa.Column("failure_reason", sa.String(255)), sa.Column("verified_via", sa.String(30)),
        sa.Column("recorded_by", sa.Integer()), sa.Column("updated_at", sa.DateTime()),
    ):
        add_column("transactions", column)
    _fk("transactions", "recorded_by", "users")
    op.execute("UPDATE transactions SET updated_at = created_at WHERE updated_at IS NULL")

    # ---- notifications / messages / reviews / disputes / buy requests ------------------------------
    add_column("notifications", sa.Column("category", sa.String(20), server_default="transactional", nullable=False))
    add_column("notifications", sa.Column("dedupe_key", sa.String(120)))
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_dedupe ON notifications (user_id, dedupe_key) "
               "WHERE dedupe_key IS NOT NULL")

    for column in (sa.Column("listing_id", sa.Integer()), sa.Column("negotiation_id", sa.Integer()),
                   sa.Column("dispute_id", sa.Integer()), sa.Column("attachment_file_id", sa.String(36)),
                   sa.Column("message_type", sa.String(20), server_default="text", nullable=False)):
        add_column("messages", column)
    _fk("messages", "listing_id", "farmer_inventory")
    _fk("messages", "negotiation_id", "negotiations")
    _fk("messages", "dispute_id", "disputes")
    _fk("messages", "attachment_file_id", "stored_files")

    for column in (sa.Column("quality_rating", sa.Integer()), sa.Column("communication_rating", sa.Integer()),
                   sa.Column("reliability_rating", sa.Integer()), sa.Column("quantity_accuracy_rating", sa.Integer()),
                   sa.Column("response", sa.String(500)), sa.Column("response_at", sa.DateTime()),
                   sa.Column("is_hidden", sa.Boolean(), server_default=sa.false(), nullable=False),
                   sa.Column("hidden_reason", sa.String(255)), sa.Column("moderated_by", sa.Integer())):
        add_column("reviews", column)
    _fk("reviews", "moderated_by", "users")

    for column in (sa.Column("resolution_type", sa.String(30)), sa.Column("refund_amount", sa.String(20)),
                   sa.Column("assigned_to", sa.Integer()),
                   sa.Column("escalated", sa.Boolean(), server_default=sa.false(), nullable=False),
                   sa.Column("escalated_at", sa.DateTime()), sa.Column("updated_at", sa.DateTime())):
        add_column("disputes", column)
    _fk("disputes", "assigned_to", "users")

    for column in (sa.Column("unit", sa.String(20), server_default="kg"), sa.Column("quality_grade", sa.String(10)),
                   sa.Column("quality_spec", sa.String(255)), sa.Column("packaging", sa.String(30))):
        add_column("buy_requests", column)
    add_column("buy_request_responses", sa.Column("shortlisted", sa.Boolean(), server_default=sa.false(), nullable=False))
    add_column("buy_request_responses", sa.Column("negotiation_id", sa.Integer()))
    _fk("buy_request_responses", "negotiation_id", "negotiations")

    # ---- catalog seed data -------------------------------------------------------------------------
    for code, name, name_te, factor in (
        ("kg", "Kilogram", "కిలోగ్రాము", "1"), ("quintal", "Quintal (100 kg)", "క్వింటాల్", "100"),
        ("tonne", "Tonne (1000 kg)", "టన్ను", "1000"), ("bag", "Bag", "బస్తా", None),
        ("crate", "Crate", "క్రేట్", None), ("dozen", "Dozen", "డజను", None),
    ):
        insert_if_missing("units", "code = :code", "code, name, name_te, kg_factor, is_active",
                          ":code, :name, :name_te, CAST(:factor AS NUMERIC), TRUE",
                          {"code": code, "name": name, "name_te": name_te, "factor": factor})
    for order, (code, name, name_te, description) in enumerate((
        ("A", "Grade A (premium)", "గ్రేడ్ A (ప్రీమియం)", "Uniform size and colour, no visible damage."),
        ("B", "Grade B (standard)", "గ్రేడ్ B (సాధారణ)", "Minor size/colour variation, minimal blemishes."),
        ("C", "Grade C (economy)", "గ్రేడ్ C (తక్కువ ధర)", "Mixed size, some blemishes; suited to processing."),
    )):
        insert_if_missing("quality_standards", "code = :code", "code, name, name_te, description, sort_order, is_active",
                          ":code, :name, :name_te, :description, :ord, TRUE",
                          {"code": code, "name": name, "name_te": name_te, "description": description, "ord": order})
    for name, name_te in (
        ("Vegetables", "కూరగాయలు"), ("Fruits", "పండ్లు"), ("Grains", "ధాన్యాలు"), ("Pulses", "పప్పుధాన్యాలు"),
        ("Spices", "సుగంధ ద్రవ్యాలు"), ("Oilseeds", "నూనెగింజలు"), ("Flowers", "పువ్వులు"),
        ("Plantation crops", "తోట పంటలు"), ("Other", "ఇతరాలు"),
    ):
        insert_if_missing("produce_categories", "name = :name", "name, name_te, is_active, created_at",
                          ":name, :name_te, TRUE, NOW()", {"name": name, "name_te": name_te})


def downgrade() -> None:
    for table in reversed(NEW_TABLES):
        if has_table(table):
            op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("DROP SEQUENCE IF EXISTS invoice_number_seq")
    op.execute("DROP INDEX IF EXISTS uq_users_email")
    op.execute("DROP INDEX IF EXISTS uq_users_phone")
    op.execute("DROP INDEX IF EXISTS uq_notifications_dedupe")
    op.execute("DROP INDEX IF EXISTS uq_orders_order_number")
    added = {
        "users": ("email", "phone", "email_verified", "phone_verified", "preferred_language", "verification_status",
                  "suspended_reason", "mfa_enabled", "mfa_secret_encrypted", "last_login_at", "deletion_requested_at",
                  "deleted_at"),
        "crops": ("category_id", "name_te", "default_unit"),
        "farmer_inventory": ("variety", "unit", "min_order_qty", "min_acceptable_price", "packaging",
                             "availability_date", "status", "reserved_qty", "sold_qty", "batch_code", "organic_claim",
                             "organic_verified", "delivery_options", "views_count", "inquiries_count",
                             "low_stock_threshold", "moderation_reason", "deleted_at"),
        "orders": ("order_number", "unit", "unit_price", "subtotal", "packaging_charge", "transport_charge",
                   "platform_fee", "tax_amount", "discount_amount", "payment_terms", "advance_amount",
                   "fulfillment_mode", "delivery_instructions", "expected_delivery_date", "negotiation_id", "offer_id",
                   "source", "terms_snapshot", "agreed_at", "farmer_confirmed_at", "vendor_confirmed_at",
                   "confirmation_deadline", "cancel_reason", "cancelled_by", "cancelled_at", "cancel_requested_by",
                   "cancel_request_reason", "cancel_requested_at", "status_before_dispute", "delivered_at", "completed_at"),
        "transactions": ("payment_method", "purpose", "reference", "failure_reason", "verified_via", "recorded_by",
                         "updated_at"),
        "notifications": ("category", "dedupe_key"),
        "messages": ("listing_id", "negotiation_id", "dispute_id", "attachment_file_id", "message_type"),
        "reviews": ("quality_rating", "communication_rating", "reliability_rating", "quantity_accuracy_rating",
                    "response", "response_at", "is_hidden", "hidden_reason", "moderated_by"),
        "disputes": ("resolution_type", "refund_amount", "assigned_to", "escalated", "escalated_at", "updated_at"),
        "buy_requests": ("unit", "quality_grade", "quality_spec", "packaging"),
        "buy_request_responses": ("shortlisted", "negotiation_id"),
    }
    for table, columns in added.items():
        for column in columns:
            drop_column(table, column)
    # Numeric type changes, widened columns, migrated order statuses and seeded lookup rows are kept.
