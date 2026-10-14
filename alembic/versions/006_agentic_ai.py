"""agentic AI layer: workflow runs, approvals, tool/model call logs, embeddings, geo, dispute reports

Requires the PostGIS and pgvector extensions (docker/postgres/Dockerfile builds an image with
both). CREATE EXTENSION needs a superuser or a role allowed to create them; on managed
PostgreSQL enable both extensions first, then run this migration.

- farmer_profiles / vendor_profiles / farmer_inventory: latitude/longitude columns plus GiST
  indexes on the geography point expression (radius matching with ST_DWithin).
- listing_embeddings: pgvector column (dimension-free so the model can change; one row per
  model version) and a GIN full-text index for the lexical half of hybrid retrieval.
- agent_* tables: durable workflow runs, append-only events, human approvals, an idempotent
  tool-call log and a model-call log.
- A separate schema (CHECKPOINT_SCHEMA, default "langgraph") for LangGraph's checkpoint tables,
  which `python -m src.agents.checkpointer setup` creates. Business data and graph checkpoints
  stay apart, and Alembic never manages the checkpointer's own tables.

Revision ID: 006
Revises: 005
Create Date: 2026-10-13

"""
import os

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from src.db_connections.migration_helpers import add_column, drop_column, has_table

revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None

CHECKPOINT_SCHEMA = os.getenv("CHECKPOINT_SCHEMA", "langgraph")

# Expression indexes managed here (and listed in alembic/env.py UNMANAGED_INDEXES).
GEO_INDEXES = (
    ("idx_farmer_profiles_geo", "farmer_profiles", "latitude", "longitude"),
    ("idx_vendor_profiles_geo", "vendor_profiles", "latitude", "longitude"),
    ("idx_listing_pickup_geo", "farmer_inventory", "pickup_latitude", "pickup_longitude"),
)


def _require_extensions():
    bind = op.get_bind()
    available = {row[0] for row in bind.execute(sa.text(
        "SELECT name FROM pg_available_extensions WHERE name IN ('postgis', 'vector')"
    ))}
    missing = {"postgis", "vector"} - available
    if missing:
        raise RuntimeError(
            f"PostgreSQL extensions not installed on the server: {', '.join(sorted(missing))}. "
            "Use the image from docker/postgres/Dockerfile (PostGIS + pgvector) or install them, then retry."
        )
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def upgrade() -> None:
    _require_extensions()
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{CHECKPOINT_SCHEMA}"')

    for table in ("farmer_profiles", "vendor_profiles"):
        add_column(table, sa.Column("latitude", sa.Numeric(9, 6), nullable=True))
        add_column(table, sa.Column("longitude", sa.Numeric(9, 6), nullable=True))
        add_column(table, sa.Column("location_source", sa.String(20), nullable=True))
    add_column("farmer_inventory", sa.Column("pickup_latitude", sa.Numeric(9, 6), nullable=True))
    add_column("farmer_inventory", sa.Column("pickup_longitude", sa.Numeric(9, 6), nullable=True))
    for name, table, lat, lon in GEO_INDEXES:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {name} ON {table} USING gist "
            f"((ST_SetSRID(ST_MakePoint({lon}::float8, {lat}::float8), 4326)::geography)) "
            f"WHERE {lat} IS NOT NULL AND {lon} IS NOT NULL"
        )

    if not has_table("agent_workflow_runs"):
        op.create_table(
            "agent_workflow_runs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("conversation_id", sa.String(36), nullable=False),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("actor_role", sa.String(10), nullable=False),
            sa.Column("workflow_type", sa.String(30), nullable=False),
            sa.Column("intent", sa.String(40)),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("current_node", sa.String(60)),
            sa.Column("pending", sa.JSON),
            sa.Column("resume_payload", sa.JSON),
            sa.Column("result", sa.JSON),
            sa.Column("error", sa.JSON),
            sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
            sa.Column("lease_owner", sa.String(64)),
            sa.Column("lease_until", sa.DateTime),
            sa.Column("next_attempt_at", sa.DateTime),
            sa.Column("waiting_on_type", sa.String(30)),
            sa.Column("waiting_on_id", sa.Integer),
            sa.Column("waiting_marker", sa.String(64)),
            sa.Column("correlation_id", sa.String(64)),
            sa.Column("created_at", sa.DateTime),
            sa.Column("updated_at", sa.DateTime),
            sa.Column("completed_at", sa.DateTime),
        )
        op.create_index("idx_agent_runs_user_created", "agent_workflow_runs", ["user_id", "created_at"])
        op.create_index("idx_agent_runs_conversation", "agent_workflow_runs", ["conversation_id"])
        op.create_index("idx_agent_runs_due", "agent_workflow_runs", ["status", "lease_until"],
                        postgresql_where=sa.text("status IN ('queued', 'running')"))
        op.create_index("idx_agent_runs_waiting", "agent_workflow_runs", ["waiting_on_type", "waiting_on_id"],
                        postgresql_where=sa.text("status = 'waiting_external'"))
        op.create_index("idx_agent_runs_status_updated", "agent_workflow_runs", ["status", "updated_at"])

    if not has_table("agent_workflow_events"):
        op.create_table(
            "agent_workflow_events",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
            sa.Column("run_id", sa.String(36), sa.ForeignKey("agent_workflow_runs.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("event_type", sa.String(30), nullable=False),
            sa.Column("node", sa.String(60)),
            sa.Column("data", sa.JSON),
            sa.Column("created_at", sa.DateTime),
        )
        op.create_index("idx_agent_events_run", "agent_workflow_events", ["run_id", "id"])
        op.create_index("idx_agent_events_created", "agent_workflow_events", ["created_at"])

    if not has_table("agent_approval_requests"):
        op.create_table(
            "agent_approval_requests",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("run_id", sa.String(36), sa.ForeignKey("agent_workflow_runs.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("step_key", sa.String(80), nullable=False),
            sa.Column("action", sa.String(40), nullable=False),
            sa.Column("requested_for", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
            sa.Column("requested_for_role", sa.String(10)),
            sa.Column("summary", sa.String(500), nullable=False),
            sa.Column("payload", sa.JSON, nullable=False),
            sa.Column("payload_hash", sa.String(64), nullable=False),
            sa.Column("editable_fields", sa.JSON),
            sa.Column("context", sa.JSON),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("reviewed_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("decision_note", sa.String(500)),
            sa.Column("expires_at", sa.DateTime),
            sa.Column("created_at", sa.DateTime),
            sa.Column("decided_at", sa.DateTime),
            sa.UniqueConstraint("run_id", "step_key", name="uq_agent_approval_step"),
        )
        op.create_index("idx_agent_approvals_user_status", "agent_approval_requests", ["requested_for", "status"])
        op.create_index("idx_agent_approvals_role_pending", "agent_approval_requests",
                        ["requested_for_role", "created_at"], postgresql_where=sa.text("status = 'pending'"))
        op.create_index("idx_agent_approvals_expiry", "agent_approval_requests", ["expires_at"],
                        postgresql_where=sa.text("status = 'pending'"))

    if not has_table("agent_tool_calls"):
        op.create_table(
            "agent_tool_calls",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
            sa.Column("run_id", sa.String(36), sa.ForeignKey("agent_workflow_runs.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approval_id", sa.Integer, sa.ForeignKey("agent_approval_requests.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("node", sa.String(60)),
            sa.Column("tool", sa.String(60), nullable=False),
            sa.Column("kind", sa.String(10), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("idempotency_key", sa.String(128)),
            sa.Column("args", sa.JSON),
            sa.Column("result", sa.JSON),
            sa.Column("error_code", sa.String(40)),
            sa.Column("error_message", sa.String(255)),
            sa.Column("latency_ms", sa.Integer),
            sa.Column("created_at", sa.DateTime),
        )
        op.create_index("uq_agent_tool_calls_idempotency", "agent_tool_calls", ["idempotency_key"], unique=True,
                        postgresql_where=sa.text("status = 'succeeded' AND idempotency_key IS NOT NULL"))
        op.create_index("idx_agent_tool_calls_run", "agent_tool_calls", ["run_id", "id"])
        op.create_index("idx_agent_tool_calls_user", "agent_tool_calls", ["user_id", "created_at"])
        op.create_index("idx_agent_tool_calls_approval", "agent_tool_calls", ["approval_id"],
                        postgresql_where=sa.text("approval_id IS NOT NULL"))
        op.create_index("idx_agent_tool_calls_created", "agent_tool_calls", ["created_at"])

    if not has_table("agent_model_calls"):
        op.create_table(
            "agent_model_calls",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
            sa.Column("run_id", sa.String(36), sa.ForeignKey("agent_workflow_runs.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("task", sa.String(40), nullable=False),
            sa.Column("provider", sa.String(30), nullable=False),
            sa.Column("model", sa.String(100), nullable=False),
            sa.Column("model_id", sa.String(60), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("error_class", sa.String(40)),
            sa.Column("attempt", sa.Integer, nullable=False, server_default="0"),
            sa.Column("fallback_rank", sa.Integer, nullable=False, server_default="0"),
            sa.Column("latency_ms", sa.Integer),
            sa.Column("input_tokens", sa.Integer),
            sa.Column("output_tokens", sa.Integer),
            sa.Column("cost_usd", sa.Numeric(12, 6)),
            sa.Column("created_at", sa.DateTime),
        )
        op.create_index("idx_agent_model_calls_run", "agent_model_calls", ["run_id"],
                        postgresql_where=sa.text("run_id IS NOT NULL"))
        op.create_index("idx_agent_model_calls_user", "agent_model_calls", ["user_id", "created_at"])
        op.create_index("idx_agent_model_calls_created", "agent_model_calls", ["created_at"])

    if not has_table("listing_embeddings"):
        op.create_table(
            "listing_embeddings",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("listing_id", sa.Integer, sa.ForeignKey("farmer_inventory.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("model_version", sa.String(160), nullable=False),
            sa.Column("dimensions", sa.Integer, nullable=False),
            sa.Column("embedding", Vector(), nullable=False),
            sa.Column("search_text", sa.Text, nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime),
            sa.Column("updated_at", sa.DateTime),
            sa.UniqueConstraint("listing_id", "model_version", name="uq_listing_embedding_model"),
        )
        op.create_index("idx_listing_embeddings_model", "listing_embeddings", ["model_version"])
        op.execute("CREATE INDEX IF NOT EXISTS idx_listing_embeddings_fts ON listing_embeddings "
                   "USING gin (to_tsvector('simple', search_text))")

    if not has_table("dispute_investigation_reports"):
        op.create_table(
            "dispute_investigation_reports",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("dispute_id", sa.Integer, sa.ForeignKey("disputes.id", ondelete="CASCADE"), nullable=False),
            sa.Column("run_id", sa.String(36), sa.ForeignKey("agent_workflow_runs.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("report", sa.JSON, nullable=False),
            sa.Column("evidence_index", sa.JSON, nullable=False),
            sa.Column("generated_by", sa.String(60), nullable=False),
            sa.Column("requires_human_review", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("reviewed_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("review_decision", sa.String(30)),
            sa.Column("review_notes", sa.String(1000)),
            sa.Column("created_at", sa.DateTime),
            sa.Column("reviewed_at", sa.DateTime),
        )
        op.create_index("idx_dispute_reports_dispute", "dispute_investigation_reports", ["dispute_id", "created_at"])
        op.create_index("idx_dispute_reports_run", "dispute_investigation_reports", ["run_id"],
                        postgresql_where=sa.text("run_id IS NOT NULL"))


def downgrade() -> None:
    for table in ("dispute_investigation_reports", "listing_embeddings", "agent_model_calls", "agent_tool_calls",
                  "agent_approval_requests", "agent_workflow_events", "agent_workflow_runs"):
        if has_table(table):
            op.drop_table(table)
    for name, *_ in GEO_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
    drop_column("farmer_inventory", "pickup_longitude")
    drop_column("farmer_inventory", "pickup_latitude")
    for table in ("vendor_profiles", "farmer_profiles"):
        drop_column(table, "location_source")
        drop_column(table, "longitude")
        drop_column(table, "latitude")
    # The checkpoint schema and the extensions are left in place: other data may depend on them.
