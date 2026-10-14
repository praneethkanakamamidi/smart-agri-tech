from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Column, String, Integer, BigInteger, DateTime, ForeignKey, Boolean, JSON, Numeric, Text, Index, UniqueConstraint,
    text,
)
from src.db_connections.postgresql_conn import Base

# Workflow run states
QUEUED = "queued"
RUNNING = "running"
AWAITING_INPUT = "awaiting_input"  # needs an answer from the user
AWAITING_APPROVAL = "awaiting_approval"  # needs the user's approval of a proposed action
WAITING_EXTERNAL = "waiting_external"  # waits for the counterparty (e.g. a reply to an offer)
ESCALATED = "escalated"  # waits for a human reviewer (admin)
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"
PAUSED_STATES = (AWAITING_INPUT, AWAITING_APPROVAL, WAITING_EXTERNAL, ESCALATED)
TERMINAL_STATES = (COMPLETED, FAILED, CANCELLED)

# Approval states
APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"
APPROVAL_EXPIRED = "expired"
APPROVAL_SUPERSEDED = "superseded"

# Tool-call outcomes
TOOL_SUCCEEDED = "succeeded"
TOOL_FAILED = "failed"
TOOL_DENIED = "denied"
TOOL_REPLAYED = "replayed"


class AgentWorkflowRuns(Base):
    """
    One agent workflow (= one LangGraph thread). The graph's own state lives in the checkpointer;
    this row is the business-side record: owner, status, what it waits for, and a lease so only
    one worker drives it at a time. The owner here - not anything in graph state - decides whose
    authority the run acts with.
    """
    __tablename__ = "agent_workflow_runs"
    __table_args__ = (
        Index("idx_agent_runs_user_created", "user_id", "created_at"),
        Index("idx_agent_runs_conversation", "conversation_id"),
        Index("idx_agent_runs_due", "status", "lease_until", postgresql_where=text("status IN ('queued', 'running')")),
        Index("idx_agent_runs_waiting", "waiting_on_type", "waiting_on_id",
              postgresql_where=text("status = 'waiting_external'")),
        Index("idx_agent_runs_status_updated", "status", "updated_at"),
    )

    id = Column(String(36), primary_key=True)  # uuid4, also the LangGraph thread_id
    conversation_id = Column(String(36), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    actor_role = Column(String(10), nullable=False)
    workflow_type = Column(String(30), nullable=False)  # chat | listing_intake | dispute_investigation
    intent = Column(String(40))
    status = Column(String(20), nullable=False)
    current_node = Column(String(60))
    pending = Column(JSON)  # what the run waits for (question, approval id, external reference)
    resume_payload = Column(JSON)  # queued resume value, consumed by the next drive
    result = Column(JSON)
    error = Column(JSON)
    attempts = Column(Integer, default=0, nullable=False)
    lease_owner = Column(String(64))
    lease_until = Column(DateTime)
    next_attempt_at = Column(DateTime)
    waiting_on_type = Column(String(30))  # negotiation | order | dispute
    waiting_on_id = Column(Integer)
    waiting_marker = Column(String(64))  # state seen when the wait began; a change wakes the run
    correlation_id = Column(String(64))
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    completed_at = Column(DateTime)


class AgentWorkflowEvents(Base):
    """Append-only, redacted trace of a run: messages, node transitions, interrupts, tool calls, errors."""
    __tablename__ = "agent_workflow_events"
    __table_args__ = (
        Index("idx_agent_events_run", "run_id", "id"),
        Index("idx_agent_events_created", "created_at"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey('agent_workflow_runs.id', ondelete='CASCADE'), nullable=False)
    event_type = Column(String(30), nullable=False)
    node = Column(String(60))
    data = Column(JSON)
    created_at = Column(DateTime)


class AgentApprovalRequests(Base):
    """
    A consequential action an agent proposes and a human must approve before it runs. The exact
    validated payload is frozen with its hash; the executing tool refuses anything that differs.
    """
    __tablename__ = "agent_approval_requests"
    __table_args__ = (
        UniqueConstraint("run_id", "step_key", name="uq_agent_approval_step"),
        Index("idx_agent_approvals_user_status", "requested_for", "status"),
        Index("idx_agent_approvals_role_pending", "requested_for_role", "created_at",
              postgresql_where=text("status = 'pending'")),
        Index("idx_agent_approvals_expiry", "expires_at", postgresql_where=text("status = 'pending'")),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey('agent_workflow_runs.id', ondelete='CASCADE'), nullable=False)
    step_key = Column(String(80), nullable=False)  # makes creation idempotent when a node re-runs
    action = Column(String(40), nullable=False)  # the tool that runs on approval
    requested_for = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=True)
    requested_for_role = Column(String(10))  # set for role queues (e.g. admin review)
    summary = Column(String(500), nullable=False)
    payload = Column(JSON, nullable=False)
    payload_hash = Column(String(64), nullable=False)
    editable_fields = Column(JSON)
    context = Column(JSON)  # facts shown to the approver (prices, stock, distances) - not executed
    status = Column(String(20), nullable=False)
    reviewed_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    decision_note = Column(String(500))
    expires_at = Column(DateTime)
    created_at = Column(DateTime)
    decided_at = Column(DateTime)


class AgentToolCalls(Base):
    """
    Every tool invocation by an agent. For mutations the row is written in the same transaction as
    the side effect, and the partial unique index on idempotency_key makes the side effect happen
    at most once per key even across retries, crashes and concurrent workers.
    """
    __tablename__ = "agent_tool_calls"
    __table_args__ = (
        Index("uq_agent_tool_calls_idempotency", "idempotency_key", unique=True,
              postgresql_where=text("status = 'succeeded' AND idempotency_key IS NOT NULL")),
        Index("idx_agent_tool_calls_run", "run_id", "id"),
        Index("idx_agent_tool_calls_user", "user_id", "created_at"),
        Index("idx_agent_tool_calls_approval", "approval_id", postgresql_where=text("approval_id IS NOT NULL")),
        Index("idx_agent_tool_calls_created", "created_at"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey('agent_workflow_runs.id', ondelete='SET NULL'), nullable=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    approval_id = Column(Integer, ForeignKey('agent_approval_requests.id', ondelete='SET NULL'), nullable=True)
    node = Column(String(60))
    tool = Column(String(60), nullable=False)
    kind = Column(String(10), nullable=False)  # read | propose | mutate
    status = Column(String(20), nullable=False)
    idempotency_key = Column(String(128))
    args = Column(JSON)  # redacted
    result = Column(JSON)
    error_code = Column(String(40))
    error_message = Column(String(255))
    latency_ms = Column(Integer)
    created_at = Column(DateTime)


class AgentModelCalls(Base):
    """One row per model call: which model served which task, latency, tokens and cost."""
    __tablename__ = "agent_model_calls"
    __table_args__ = (
        Index("idx_agent_model_calls_run", "run_id", postgresql_where=text("run_id IS NOT NULL")),
        Index("idx_agent_model_calls_user", "user_id", "created_at"),
        Index("idx_agent_model_calls_created", "created_at"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey('agent_workflow_runs.id', ondelete='SET NULL'), nullable=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    task = Column(String(40), nullable=False)
    provider = Column(String(30), nullable=False)
    model = Column(String(100), nullable=False)
    model_id = Column(String(60), nullable=False)
    status = Column(String(20), nullable=False)  # ok | error
    error_class = Column(String(40))
    attempt = Column(Integer, nullable=False, default=0)
    fallback_rank = Column(Integer, nullable=False, default=0)
    latency_ms = Column(Integer)
    input_tokens = Column(Integer)
    output_tokens = Column(Integer)
    cost_usd = Column(Numeric(12, 6))
    created_at = Column(DateTime)


class ListingEmbeddings(Base):
    """
    Semantic index of listings. One row per (listing, embedding model version) so a model change
    can be re-indexed side by side and switched over. Stale rows (content_hash differs from the
    listing's current text) are refreshed by the indexer; queries always join the live listing,
    so expired, sold or removed listings can't surface from a stale vector.
    """
    __tablename__ = "listing_embeddings"
    __table_args__ = (
        UniqueConstraint("listing_id", "model_version", name="uq_listing_embedding_model"),
        Index("idx_listing_embeddings_model", "model_version"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    listing_id = Column(Integer, ForeignKey('farmer_inventory.id', ondelete='CASCADE'), nullable=False)
    model_version = Column(String(160), nullable=False)
    dimensions = Column(Integer, nullable=False)
    embedding = Column(Vector(), nullable=False)  # L2-normalised; cosine distance via <=>
    search_text = Column(Text, nullable=False)  # also feeds the lexical (full-text) index
    content_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class DisputeInvestigationReports(Base):
    """Evidence-linked investigation report drafted by the dispute agent for an admin to review."""
    __tablename__ = "dispute_investigation_reports"
    __table_args__ = (
        Index("idx_dispute_reports_dispute", "dispute_id", "created_at"),
        Index("idx_dispute_reports_run", "run_id", postgresql_where=text("run_id IS NOT NULL")),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    dispute_id = Column(Integer, ForeignKey('disputes.id', ondelete='CASCADE'), nullable=False)
    run_id = Column(String(36), ForeignKey('agent_workflow_runs.id', ondelete='SET NULL'), nullable=True)
    status = Column(String(20), nullable=False)  # pending_review | reviewed
    report = Column(JSON, nullable=False)
    evidence_index = Column(JSON, nullable=False)  # ref -> source record description
    generated_by = Column(String(60), nullable=False)  # model id, or "rules"
    requires_human_review = Column(Boolean, default=True, nullable=False)
    reviewed_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    review_decision = Column(String(30))
    review_notes = Column(String(1000))
    created_at = Column(DateTime)
    reviewed_at = Column(DateTime)


__all__ = [
    "AgentWorkflowRuns", "AgentWorkflowEvents", "AgentApprovalRequests", "AgentToolCalls", "AgentModelCalls",
    "ListingEmbeddings", "DisputeInvestigationReports",
]
