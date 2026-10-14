"""
Shared graph state. JSON-serialisable values only, and only what the workflow needs to
continue: record ids and small summaries, never whole database rows, images or secrets.
Business truth stays in PostgreSQL; nodes re-read it through tools when they need it.

`authenticated_user_id` / `actor_role` are informational copies for traces. Authorization
always uses the runtime RunContext built by the runner from the database.
"""
from typing import Annotated, TypedDict

MAX_LIST = 40


def append_capped(left: list | None, right: list | None) -> list:
    return ((left or []) + (right or []))[-MAX_LIST:]


def merge_dicts(left: dict | None, right: dict | None) -> dict:
    return {**(left or {}), **(right or {})}


class WorkflowState(TypedDict, total=False):
    workflow_id: str
    conversation_id: str
    correlation_id: str
    authenticated_user_id: int
    actor_role: str
    workflow_type: str  # chat | listing_intake | dispute_investigation

    messages: Annotated[list[dict], append_capped]  # {"role": "user"|"assistant", "content": str}
    carry_over: dict  # context from the previous run in this conversation (ids and summaries)

    intent: str
    understanding: dict  # RequestUnderstanding, JSON
    understanding_source: str  # llm | rules
    plan: list[str]  # remaining specialist nodes
    next: str  # the node to run next (validated against the graph's path map)
    pending_question: str | None
    clarifications: int

    normalized_request: dict
    selected_listing_id: int | None
    selected_supplier_id: int | None
    candidate_matches: list[dict]  # [{listing_id, farmer_id, crop_name, asking_price, unit, score}]
    negotiation: dict  # {negotiation_id, offer_id, round, my_last_price, status}
    order: dict  # {order_id, order_number, status}
    dispute: dict  # {dispute_id, report_id}
    file_ids: list[str]
    evidence_refs: list[str]
    listing_draft: dict

    agent_results: Annotated[dict, merge_dicts]  # node -> summary of what it found/did
    confidence: float
    uncertainty: Annotated[list[str], append_capped]
    pending_approval: dict | None  # {approval_id, action, summary, payload, status}
    errors: Annotated[list[dict], append_capped]
    security_flags: Annotated[list[str], append_capped]
    visited: Annotated[list[str], append_capped]
    step_count: int
    status: str
    response: dict
