"""Helpers shared by graph nodes: step accounting, plan advancement, tool calls, approvals."""
from langgraph.runtime import Runtime

from src.agents.config import settings
from src.agents.context import RunContext
from src.agents.domain.understanding import RequestUnderstanding
from src.agents.state import WorkflowState
from src.agents.tools.base import ToolError

# Approval-gated action -> the node that executes it after approval.
EXECUTE_NODE = {
    "submit_offer": "negotiation_execute",
    "respond_to_offer": "negotiation_execute",
    "create_order": "negotiation_execute",
    "create_listing": "create_listing_execute",
    "confirm_order": "logistics_execute",
    "schedule_pickup": "logistics_execute",
    "resolve_dispute": "dispute_resolve_execute",
}


class StepLimitReached(Exception):
    pass


def ctx_of(runtime: Runtime[RunContext], node: str) -> RunContext:
    return runtime.context.at(node)


def enter(state: WorkflowState, node: str) -> dict:
    """Count a step. Past AGENT_MAX_STEPS the workflow stops instead of looping."""
    steps = (state.get("step_count") or 0) + 1
    if steps > settings().max_steps:
        raise StepLimitReached(f"step limit {settings().max_steps} reached at {node}")
    return {"step_count": steps, "visited": [node]}


def understanding(state: WorkflowState) -> RequestUnderstanding:
    return RequestUnderstanding.model_validate(state.get("understanding") or {"intent": "unknown", "confidence": 0})


def advance(state: WorkflowState, updates: dict | None = None) -> dict:
    """Move to the next planned specialist, or to `respond` when the plan is done."""
    plan = list((updates or {}).get("plan", state.get("plan") or []))
    nxt = plan.pop(0) if plan else "respond"
    return {**(updates or {}), "plan": plan, "next": nxt}


def last_user_text(state: WorkflowState) -> str:
    for message in reversed(state.get("messages") or []):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


async def call(runtime: Runtime[RunContext], node: str, tool: str, args, **kw) -> dict:
    ctx = ctx_of(runtime, node)
    return await ctx.tools.call(ctx, tool, args, **kw)


def tool_error(node: str, tool: str, error: ToolError) -> dict:
    return {"node": node, "tool": tool, **error.as_dict()}


async def propose(runtime: Runtime[RunContext], node: str, *, action: str, step_key: str, payload: dict,
                  summary: str, editable_fields: list[str], context: dict, requested_for_role: str | None = None) -> dict:
    """Create (or fetch, on re-run) the approval request and route to the waiting node."""
    approval = await call(runtime, node, "request_human_approval", {
        "action": action, "step_key": step_key, "payload": payload, "summary": summary[:500],
        "editable_fields": editable_fields, "context": context, "requested_for_role": requested_for_role,
    })
    return {
        "pending_approval": {"approval_id": approval["approval_id"], "action": action, "summary": approval["summary"],
                             "payload": approval["payload"], "status": approval["status"],
                             "requested_for_role": requested_for_role},
        "next": "await_approval",
    }


def money_str(value) -> str:
    try:
        return f"{float(value):,.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)
