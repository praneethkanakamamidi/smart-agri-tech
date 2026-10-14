"""
Supervisor: understand the request, check the role may do it, ask for anything essential that
is missing, and route to the specialists in the plan. Also the generic interrupt nodes for
clarifying questions and human approvals.
"""
import json

from langgraph.runtime import Runtime
from langgraph.types import interrupt

from src.agents.context import RunContext
from src.agents.domain.understanding import (
    UNDERSTANDING_SYSTEM_PROMPT, RequestUnderstanding, build_plan, missing_for, rules_understanding,
)
from src.agents.llm import Message, TaskType
from src.agents.llm.errors import LLMError
from src.agents.nodes.common import EXECUTE_NODE, advance, call, ctx_of, enter, last_user_text, tool_error
from src.agents.policy import UNTRUSTED_DATA_RULES, detect_prompt_injection, intent_allowed, wrap_untrusted
from src.agents.state import WorkflowState
from src.agents.tools.base import ToolError
from src.helpers.logging_config import get_logger

logger = get_logger("agents.supervisor")
MAX_CLARIFICATIONS = 3
FORCED_INTENTS = {"listing_intake": "create_listing", "dispute_investigation": "investigate_dispute"}


def _merge(prior: dict | None, new: RequestUnderstanding) -> RequestUnderstanding:
    """A clarification answer fills gaps; it doesn't wipe what the user already said."""
    if not prior:
        return new
    base = RequestUnderstanding.model_validate(prior)
    data = base.model_dump()
    for key, value in new.model_dump().items():
        if key in ("missing_information", "clarifying_question"):
            continue
        if value not in (None, [], "", "none", False) and not (key == "intent" and value == "unknown"):
            data[key] = value
    if base.intent != "unknown" and new.intent in ("unknown", "general_question"):
        data["intent"] = base.intent
    data["confidence"] = max(base.confidence, new.confidence)
    merged = RequestUnderstanding.model_validate(data)
    missing = missing_for(merged)
    merged.missing_information = [m[0] for m in missing]
    merged.clarifying_question = missing[0][1] if missing else None
    return merged


async def _llm_understanding(ctx: RunContext, state: WorkflowState, text: str) -> RequestUnderstanding:
    context = {
        "role": ctx.role,
        "previous_understanding": state.get("understanding"),
        "previous_candidates": [
            {"listing_id": c["listing_id"], "crop": c.get("crop_name"), "asking_price": c.get("asking_price")}
            for c in (state.get("carry_over") or {}).get("candidate_matches", [])[:10]
        ],
        "pending_question": state.get("pending_question"),
    }
    parsed, _ = await ctx.llm.structured(
        TaskType.INTENT_CLASSIFICATION, RequestUnderstanding,
        [Message.user("Conversation context (trusted, from the server):\n" + json.dumps(context, default=str)
                      + "\n\nThe user's latest message:\n" + wrap_untrusted("user_message", text))],
        system=UNDERSTANDING_SYSTEM_PROMPT + "\n\n" + UNTRUSTED_DATA_RULES,
        run_id=ctx.run_id, user_id=ctx.user_id,
    )
    return parsed


async def _rules_understanding(runtime, text: str) -> RequestUnderstanding:
    parsed = await call(runtime, "understand", "parse_request_rules", {"text": text[:2000]})
    return rules_understanding(text, parsed["filters"], parsed["crop_names"])


async def understand(state: WorkflowState, runtime: Runtime[RunContext]) -> dict:
    updates = enter(state, "understand")
    ctx = ctx_of(runtime, "understand")
    text = last_user_text(state)
    flags = detect_prompt_injection(text)
    if flags:
        logger.warning("prompt-injection signals in user message", extra={"run_id": ctx.run_id, "signals": flags})

    source = "rules"
    try:
        if ctx.llm and ctx.llm.can_serve(TaskType.INTENT_CLASSIFICATION, structured=True):
            new = await _llm_understanding(ctx, state, text)
            source = "llm"
        else:
            new = await _rules_understanding(runtime, text)
    except LLMError as e:
        logger.warning(f"understanding fell back to rules: {e.code}")
        updates["errors"] = [{"node": "understand", "code": e.code, "message": "model unavailable; used rules"}]
        new = await _rules_understanding(runtime, text)
    except ToolError as e:
        return {**updates, "errors": [tool_error("understand", "parse_request_rules", e)], "next": "respond"}

    forced = FORCED_INTENTS.get(state.get("workflow_type") or "")
    if forced:
        new.intent = forced
        if forced == "investigate_dispute" and not new.dispute_id and (state.get("dispute") or {}).get("dispute_id"):
            new.dispute_id = state["dispute"]["dispute_id"]
        missing = missing_for(new)
        new.missing_information = [m[0] for m in missing]
        new.clarifying_question = missing[0][1] if missing else None
    u = _merge(state.get("understanding") if state.get("pending_question") else None, new)

    updates.update(understanding=u.model_dump(mode="json"), understanding_source=source, intent=u.intent,
                   confidence=u.confidence, pending_question=None, security_flags=flags)
    if not intent_allowed(ctx.role, u.intent):
        updates["agent_results"] = {"policy": {"refused": True, "intent": u.intent,
                                               "reason": f"A {ctx.role} account can't do that here."}}
        return {**updates, "plan": [], "next": "respond"}
    if u.missing_information and (state.get("clarifications") or 0) < MAX_CLARIFICATIONS:
        question = u.clarifying_question or "Could you add a little more detail?"
        return {**updates, "pending_question": question, "next": "clarify"}
    if u.missing_information:
        updates["uncertainty"] = [f"still missing: {', '.join(u.missing_information)}"]
        return {**updates, "plan": [], "next": "respond"}
    if u.listing_id:
        updates["selected_listing_id"] = u.listing_id
    if u.negotiation_id:
        updates["negotiation"] = {**(state.get("negotiation") or {}), "negotiation_id": u.negotiation_id}
    if u.order_id:
        updates["order"] = {**(state.get("order") or {}), "order_id": u.order_id}
    if u.dispute_id:
        updates["dispute"] = {**(state.get("dispute") or {}), "dispute_id": u.dispute_id}
    plan = build_plan(u, has_images=bool(state.get("file_ids")))
    return advance(state, {**updates, "plan": plan})


async def clarify(state: WorkflowState, runtime: Runtime[RunContext]) -> dict:
    question = state.get("pending_question") or "Could you add a little more detail?"
    answer = interrupt({"type": "input", "question": question,
                        "missing": (state.get("understanding") or {}).get("missing_information", [])})
    text = str((answer or {}).get("text") or "").strip()[:2000]
    return {"messages": [{"role": "user", "content": text}], "clarifications": (state.get("clarifications") or 0) + 1,
            "next": "understand"}


async def await_approval(state: WorkflowState, runtime: Runtime[RunContext]) -> dict:
    """Pause until the approver decides. The runner resumes with the decision read from the database."""
    pending = state.get("pending_approval") or {}
    decision = interrupt({"type": "approval", "approval_id": pending.get("approval_id"), "action": pending.get("action"),
                          "summary": pending.get("summary"), "requested_for_role": pending.get("requested_for_role")})
    decision = decision or {}
    if decision.get("approval_id") != pending.get("approval_id"):
        return {"errors": [{"node": "await_approval", "code": "approval_mismatch",
                            "message": "resumed with a different approval"}], "next": "respond"}
    if decision.get("decision") != "approved":
        return {"pending_approval": {**pending, "status": decision.get("decision", "rejected")},
                "agent_results": {"approval": {"action": pending.get("action"), "status": decision.get("decision"),
                                               "note": decision.get("note")}},
                "plan": [], "next": "respond"}
    return {"pending_approval": {**pending, "status": "approved", "payload": decision.get("payload", pending.get("payload"))},
            "next": EXECUTE_NODE[pending["action"]]}
