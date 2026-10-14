"""
Negotiation specialist.

  negotiation_prepare  -> compute the price deterministically (domain/pricing.py), optionally let
                          a model draft the message, then ask the user to approve the exact offer
  await_approval       -> (supervisor) pause until the user decides
  negotiation_execute  -> run the approved tool (submit_offer / create_order / respond_to_offer)
  await_counterparty   -> pause until the other party acts (the run is woken by the worker)
  negotiation_review   -> read what happened and propose the next step, within the user's limits

A model never sets a price: it only drafts text, and a draft that quotes any other amount is
discarded in favour of a template.
"""
import re
from decimal import Decimal

from langgraph.runtime import Runtime
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from src.agents.config import settings
from src.agents.context import RunContext
from src.agents.domain.pricing import MarketBand, farmer_response, opening_offer, validate_terms, vendor_response
from src.agents.llm import Message, TaskType
from src.agents.llm.errors import LLMError
from src.agents.nodes.common import advance, call, ctx_of, enter, money_str, propose, tool_error, understanding
from src.agents.policy import UNTRUSTED_DATA_RULES
from src.agents.state import WorkflowState
from src.agents.tools.base import ToolError
from src.core.money import D
from src.security_utils.role_guard import VENDOR


class OfferMessage(BaseModel):
    message: str = Field(..., max_length=600, description="Short, polite note to the counterparty.")
    tradeoffs: list[str] = Field(default_factory=list, max_length=4, description="Points for the user, not sent.")


_AMOUNT = re.compile(r"(?:₹|rs\.?|inr)\s*(\d+(?:[.,]\d+)?)", re.I)


def message_consistent(message: str, price: Decimal) -> bool:
    for amount in _AMOUNT.findall(message or ""):
        if abs(D(amount.replace(",", "")) - D(price)) > Decimal("0.01"):
            return False
    return True


def template_message(role: str, quantity, unit: str, price, crop: str, counter: bool) -> str:
    if role == VENDOR:
        return (f"{'Counteroffer' if counter else 'Offer'}: {money_str(quantity)} {unit} of {crop} at "
                f"₹{money_str(price)}/{unit}. Happy to discuss pickup timing.")
    return f"I can do ₹{money_str(price)}/{unit} for {money_str(quantity)} {unit} of {crop}."


async def draft_message(ctx: RunContext, facts: dict, price: Decimal, fallback: str) -> tuple[str, list[str], str]:
    if not (settings().llm_responses and ctx.llm and ctx.llm.can_serve(TaskType.NEGOTIATION, structured=True)):
        return fallback, [], "template"
    try:
        parsed, response = await ctx.llm.structured(
            TaskType.NEGOTIATION, OfferMessage,
            [Message.user("Draft the note that accompanies this offer, and list the main trade-offs for the "
                          f"user. Use exactly this price if you mention one: ₹{price}. Facts: {facts}")],
            system=("You help a farmer or vendor negotiate on an agricultural marketplace. Be brief, polite and "
                    "factual. Never promise anything not in the facts, never mention private limits, never "
                    "claim the other side will accept. " + UNTRUSTED_DATA_RULES),
            run_id=ctx.run_id, user_id=ctx.user_id,
        )
    except LLMError:
        return fallback, [], "template"
    if not message_consistent(parsed.message, price):
        return fallback, parsed.tradeoffs, "template (model draft quoted a different price)"
    return parsed.message.strip(), parsed.tradeoffs, response.model_id


async def _band(runtime, node: str, crop_id: int, unit: str) -> tuple[MarketBand, dict | None]:
    try:
        insights = await call(runtime, node, "retrieve_market_price_data", {"crop_id": crop_id, "unit": unit, "days": 60})
        return MarketBand.from_insights(insights), insights.get("negotiated_prices")
    except ToolError:
        return MarketBand(), None


async def _vendor_opening(state: WorkflowState, runtime, updates: dict) -> dict:
    ctx = ctx_of(runtime, "negotiation_prepare")
    u = understanding(state)
    listing_id = state.get("selected_listing_id") or u.listing_id
    listing = await call(runtime, "negotiation_prepare", "get_listing_details", {"listing_id": listing_id})
    asking, available = D(listing["asking_price"]), D(listing["available_quantity"])
    unit, crop = listing["unit"], listing.get("crop_name") or "produce"
    quantity = D(u.quantity) if u.quantity else None
    if quantity is None:
        return {**updates, "pending_question": f"How many {unit} of {crop} do you want to offer for?", "next": "clarify"}
    if u.unit and u.unit != unit:
        return {**updates, "agent_results": {"negotiation": {
            "blocked": f"You asked in {u.unit} but this listing is priced per {unit}. Restate the quantity in {unit}."}},
            "next": "respond"}
    band, deals = await _band(runtime, "negotiation_prepare", listing["crop"], unit)
    max_price = D(u.max_price_per_unit) if u.max_price_per_unit else None
    decision = opening_offer(asking, band, target=D(u.target_price_per_unit) if u.target_price_per_unit else None,
                             max_price=max_price)
    if decision.action != "offer":
        return {**updates, "agent_results": {"negotiation": {"blocked": "; ".join(decision.rationale)}}, "next": "respond"}
    problems = validate_terms(unit_price=decision.unit_price, quantity=quantity, available=available,
                              min_order=D(listing["min_order_qty"]) if listing.get("min_order_qty") else None,
                              max_price=max_price)
    if problems:
        return {**updates, "agent_results": {"negotiation": {"blocked": "; ".join(problems)}}, "next": "respond"}
    facts = {"crop": crop, "quantity": str(quantity), "unit": unit, "asking_price": str(asking),
             "offer_price": str(decision.unit_price), "rationale": decision.rationale}
    message, tradeoffs, drafted_by = await draft_message(
        ctx, facts, decision.unit_price, template_message(VENDOR, quantity, unit, decision.unit_price, crop, False))
    delivery = u.delivery_option if u.delivery_option in (listing.get("delivery_options") or []) else None
    payload = {"listing_id": listing_id, "quantity": float(quantity), "unit_price": float(decision.unit_price),
               "delivery_preference": delivery, "message": message}
    proposal = await propose(
        runtime, "negotiation_prepare", action="submit_offer", step_key=f"offer:listing:{listing_id}:1",
        payload=payload,
        summary=(f"Send an offer to {listing.get('farmer_name') or 'the farmer'}: {money_str(quantity)} {unit} of {crop} at "
                 f"₹{money_str(decision.unit_price)}/{unit} (asking ₹{money_str(asking)}/{unit}, "
                 f"total ₹{money_str(quantity * decision.unit_price)})."),
        editable_fields=["unit_price", "quantity", "message"],
        context={"asking_price": str(asking), "available": str(available), "rationale": decision.rationale,
                 "market": deals, "tradeoffs": tradeoffs, "message_drafted_by": drafted_by,
                 "your_max_price": str(max_price) if max_price else None},
    )
    return {**updates, **proposal, "negotiation": {"listing_id": listing_id, "round": 1, "crop": crop, "unit": unit},
            "agent_results": {"negotiation": {"proposed": decision.as_dict(), "listing_id": listing_id}}}


async def _respond_to_current(state: WorkflowState, runtime, updates: dict, history: dict, round_no: int) -> dict:
    """Propose accept / counter / reject for the offer that is waiting on this user."""
    ctx = ctx_of(runtime, "negotiation_review")
    u = understanding(state)
    neg = state.get("negotiation") or {}
    current, listing = history["current_offer"], history["listing"]
    nid, unit, crop = history["id"], listing["unit"], listing.get("crop_name") or "produce"
    price, quantity = D(current["unit_price"]), D(current["quantity"])
    mine = [o for o in history["history"] if o.get("is_mine")]
    my_last = D(mine[-1]["unit_price"]) if mine else None
    try:
        details = await call(runtime, "negotiation_review", "get_listing_details", {"listing_id": history["listing_id"]})
        band, deals = await _band(runtime, "negotiation_review", details["crop"], unit)
    except ToolError:  # e.g. the listing was paused: decide without a market band
        band, deals = MarketBand(), None
    max_rounds = settings().max_negotiation_rounds
    explicit = u.action_hint if u.action_hint in ("accept", "reject", "counter") else None

    if ctx.role == VENDOR:
        decision = vendor_response(price, my_last, max_price=D(u.max_price_per_unit) if u.max_price_per_unit else None,
                                   band=band, round_no=round_no, max_rounds=max_rounds)
    else:
        floor = listing.get("my_minimum_acceptable_price")
        decision = farmer_response(price, D(listing["asking_price"]), my_last,
                                   floor=D(floor) if floor is not None else None, band=band,
                                   round_no=round_no, max_rounds=max_rounds)
    action = explicit or decision.action
    if explicit == "counter" and u.target_price_per_unit:
        decision.unit_price = D(u.target_price_per_unit)
        decision.rationale = ["the price you asked for"]
    results = {"negotiation": {"negotiation_id": nid, "their_offer": str(price), "quantity": str(quantity),
                               "unit": unit, "round": round_no, "recommendation": decision.as_dict()}}
    if action == "accept":
        return {**updates, **await propose(
            runtime, "negotiation_review", action="create_order", step_key=f"accept:{nid}:{current['id']}",
            payload={"negotiation_id": nid, "offer_id": current["id"]},
            summary=(f"Accept the offer of ₹{money_str(price)}/{unit} for {money_str(quantity)} {unit} of {crop} "
                     f"(total ₹{money_str(price * quantity)}). This creates a binding order and reserves the stock."),
            editable_fields=["payment_terms", "delivery_instructions"],
            context={"rationale": decision.rationale, "their_offer": str(price), "your_last": str(my_last) if my_last else None},
        ), "agent_results": results}
    if action == "reject":
        return {**updates, **await propose(
            runtime, "negotiation_review", action="respond_to_offer", step_key=f"reject:{nid}:{current['id']}",
            payload={"negotiation_id": nid, "offer_id": current["id"], "action": "reject", "reason": None},
            summary=f"Reject the offer of ₹{money_str(price)}/{unit} for {crop}. This closes the negotiation.",
            editable_fields=["reason"], context={"their_offer": str(price)},
        ), "agent_results": results}
    if action == "counter" and decision.unit_price:
        facts = {"crop": crop, "quantity": str(quantity), "unit": unit, "their_offer": str(price),
                 "counter_price": str(decision.unit_price), "rationale": decision.rationale}
        message, tradeoffs, drafted_by = await draft_message(
            ctx, facts, decision.unit_price, template_message(ctx.role, quantity, unit, decision.unit_price, crop, True))
        return {**updates, **await propose(
            runtime, "negotiation_review", action="submit_offer", step_key=f"counter:{nid}:{current['id']}",
            payload={"negotiation_id": nid, "quantity": float(quantity), "unit_price": float(decision.unit_price),
                     "message": message},
            summary=(f"Counter at ₹{money_str(decision.unit_price)}/{unit} for {money_str(quantity)} {unit} of {crop} "
                     f"(they offered ₹{money_str(price)})."),
            editable_fields=["unit_price", "quantity", "message"],
            context={"rationale": decision.rationale, "tradeoffs": tradeoffs, "message_drafted_by": drafted_by,
                     "market": deals},
        ), "negotiation": {**neg, "negotiation_id": nid, "round": round_no}, "agent_results": results}
    results["negotiation"]["needs_your_decision"] = True
    return {**updates, "agent_results": results, "next": "respond"}


async def negotiation_prepare(state: WorkflowState, runtime: Runtime[RunContext]) -> dict:
    updates = enter(state, "negotiation_prepare")
    ctx = ctx_of(runtime, "negotiation_prepare")
    nid = (state.get("negotiation") or {}).get("negotiation_id")
    try:
        if nid:
            history = await call(runtime, "negotiation_prepare", "get_offer_history", {"negotiation_id": nid})
            current = history.get("current_offer")
            if not current or not current.get("is_actionable_by_me"):
                return {**updates, "agent_results": {"negotiation": {
                    "negotiation_id": nid, "status": history["status"],
                    "note": "No offer is waiting for your response in this negotiation."}}, "next": "respond"}
            round_no = (state.get("negotiation") or {}).get("round") or len([o for o in history["history"] if o.get("is_mine")]) + 1
            return await _respond_to_current(state, runtime, updates, history, round_no)
        if ctx.role != VENDOR:
            return {**updates, "agent_results": {"negotiation": {
                "note": "Farmers respond to offers; say which negotiation number to respond to."}}, "next": "respond"}
        if not (state.get("selected_listing_id") or understanding(state).listing_id):
            return {**updates, "agent_results": {"negotiation": {"note": "No listing to make an offer on."}}, "next": "respond"}
        return await _vendor_opening(state, runtime, updates)
    except ToolError as e:
        return {**updates, "errors": [tool_error("negotiation_prepare", "negotiation", e)], "next": "respond"}


async def negotiation_execute(state: WorkflowState, runtime: Runtime[RunContext]) -> dict:
    updates = enter(state, "negotiation_execute")
    pending = state["pending_approval"]
    neg = dict(state.get("negotiation") or {})
    try:
        result = await call(runtime, "negotiation_execute", pending["action"], pending["payload"],
                            approval_id=pending["approval_id"])
    except ToolError as e:
        return {**updates, "errors": [tool_error("negotiation_execute", pending["action"], e)],
                "agent_results": {"negotiation": {"failed": e.message}}, "next": "respond"}
    if pending["action"] == "submit_offer":
        neg.update(negotiation_id=result.get("negotiation_id") or pending["payload"].get("negotiation_id"),
                   offer_id=result.get("offer_id"), my_last_price=str(pending["payload"]["unit_price"]),
                   status="PENDING", round=neg.get("round") or 1)
        return {**updates, "negotiation": neg, "pending_approval": None,
                "agent_results": {"negotiation": {"sent": {"offer_id": result.get("offer_id"),
                                                           "expires_at": str(result.get("expires_at")),
                                                           "unit_price": pending["payload"]["unit_price"]}}},
                "next": "await_counterparty"}
    if pending["action"] == "create_order":
        order = {"order_id": result.get("order_id"), "order_number": result.get("order_number"),
                 "status": result.get("status")}
        return advance(state, {**updates, "order": order, "pending_approval": None,
                               "negotiation": {**neg, "status": "ACCEPTED"},
                               "agent_results": {"negotiation": {"accepted": True, **order,
                                                                 "total_payable": str(result.get("total_payable"))}},
                               "plan": ["order_logistics"]})
    return {**updates, "pending_approval": None, "negotiation": {**neg, "status": "REJECTED"},
            "agent_results": {"negotiation": {"rejected": True}}, "next": "respond"}


async def await_counterparty(state: WorkflowState, runtime: Runtime[RunContext]) -> dict:
    neg = state.get("negotiation") or {}
    event = interrupt({"type": "external", "waiting_on": "negotiation", "negotiation_id": neg.get("negotiation_id"),
                       "offer_id": neg.get("offer_id"),
                       "summary": "Waiting for the other party to accept, counter or reject your offer."})
    return {"negotiation": {**neg, "last_event": (event or {}).get("event")}, "next": "negotiation_review"}


async def negotiation_review(state: WorkflowState, runtime: Runtime[RunContext]) -> dict:
    updates = enter(state, "negotiation_review")
    neg = dict(state.get("negotiation") or {})
    try:
        history = await call(runtime, "negotiation_review", "get_offer_history", {"negotiation_id": neg["negotiation_id"]})
    except ToolError as e:
        return {**updates, "errors": [tool_error("negotiation_review", "get_offer_history", e)], "next": "respond"}
    status, current = history["status"], history.get("current_offer")
    if status == "ACCEPTED" and history.get("order_id"):
        order = {"order_id": history["order_id"], "status": "pending_confirmation"}
        return advance(state, {**updates, "order": order, "negotiation": {**neg, "status": status},
                               "agent_results": {"negotiation": {"accepted_by_counterparty": True, **order}},
                               "plan": ["order_logistics"]})
    if status in ("REJECTED", "CANCELLED"):
        return {**updates, "negotiation": {**neg, "status": status},
                "agent_results": {"negotiation": {"closed": status.lower(), "reason": history.get("cancel_reason")}},
                "next": "respond"}
    if current and current.get("is_actionable_by_me"):
        round_no = int(neg.get("round") or 1) + 1
        neg["round"] = round_no
        return await _respond_to_current({**state, "negotiation": neg}, runtime, {**updates, "negotiation": neg},
                                         history, round_no)
    if status == "EXPIRED" or (current and current.get("status") == "EXPIRED"):
        return {**updates, "negotiation": {**neg, "status": "EXPIRED"},
                "agent_results": {"negotiation": {"expired": True, "note": "The offer expired without a response."}},
                "next": "respond"}
    return {**updates, "next": "await_counterparty"}  # woken without a relevant change: keep waiting


async def negotiation_status(state: WorkflowState, runtime: Runtime[RunContext]) -> dict:
    updates = enter(state, "negotiation_status")
    nid = (state.get("negotiation") or {}).get("negotiation_id")
    if not nid:
        return advance(state, {**updates, "uncertainty": ["no negotiation number given"]})
    try:
        history = await call(runtime, "negotiation_status", "get_offer_history", {"negotiation_id": nid})
    except ToolError as e:
        return advance(state, {**updates, "errors": [tool_error("negotiation_status", "get_offer_history", e)]})
    current = history.get("current_offer") or {}
    return advance(state, {**updates, "agent_results": {"negotiation": {
        "negotiation_id": nid, "status": history["status"], "listing": history["listing"].get("crop_name"),
        "asking_price": str(history["listing"].get("asking_price")),
        "current_offer": {k: str(current.get(k)) for k in ("unit_price", "quantity", "status", "expires_at") if current},
        "your_turn": bool(current.get("is_actionable_by_me")), "offers": len(history["history"]),
        "order_id": history.get("order_id"),
    }}})
