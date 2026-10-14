"""
Final answer. The message is composed deterministically from what the tools returned; a model
may rephrase it (and translate it to the user's language), but a rephrasing that contains any
number not present in the facts is rejected - the model can't add prices, quantities or ids.
"""
import json
import re

from langgraph.runtime import Runtime
from pydantic import BaseModel, Field

from src.agents.config import settings
from src.agents.context import RunContext
from src.agents.llm import Message, TaskType
from src.agents.llm.errors import LLMError
from src.agents.nodes.common import money_str
from src.agents.policy import NEVER_AUTOMATED, UNTRUSTED_DATA_RULES
from src.agents.state import WorkflowState

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


class FinalAnswer(BaseModel):
    message: str = Field(..., max_length=1500)


def _discovery(r: dict) -> list[str]:
    if not r.get("match_count"):
        return ["I couldn't find live listings that meet all your requirements."
                + (" " + " ".join(r.get("notes", [])) if r.get("notes") else "")]
    lines = [f"I found {r['match_count']} matching listing(s)" + (" (none can fill the full quantity, so these are partial)"
                                                                 if r.get("partial_matches_only") else "") + ":"]
    for i, m in enumerate(r["matches"][:5], 1):
        where = f", {m['distance_km']:.0f} km away" if m.get("distance_km") is not None else ""
        lines.append(f"{i}. Listing #{m['listing_id']}: {m['crop_name']}{' ' + m['variety'] if m.get('variety') else ''}, "
                     f"{money_str(m['available_quantity'])} {m['unit']} at ₹{money_str(m['asking_price'])}/{m['unit']}"
                     f"{', grade ' + m['quality_grade'] if m.get('quality_grade') else ''}{where}.")
    lines += r.get("notes", [])
    lines.append("Prices shown are asking prices; the final price is negotiated.")
    return lines


def _negotiation(r: dict) -> list[str]:
    if r.get("blocked"):
        return [f"I can't prepare that offer: {r['blocked']}."]
    if r.get("failed"):
        return [f"The action didn't go through: {r['failed']}"]
    if r.get("accepted") or r.get("accepted_by_counterparty"):
        who = "The other party accepted" if r.get("accepted_by_counterparty") else "Accepted"
        return [f"{who}: order {r.get('order_number') or '#' + str(r.get('order_id'))} was created and the stock is reserved."]
    if r.get("rejected"):
        return ["The offer was rejected and the negotiation is closed."]
    if r.get("closed"):
        return [f"The negotiation was {r['closed']}."]
    if r.get("expired"):
        return [r.get("note") or "The offer expired."]
    if r.get("sent"):
        return [f"Offer sent at ₹{money_str(r['sent']['unit_price'])} per unit. I'll pick this up when the other party responds."]
    if r.get("needs_your_decision"):
        rec = r.get("recommendation", {})
        return [f"They offered ₹{money_str(r.get('their_offer'))}/{r.get('unit')}. I won't go further on my own: "
                + "; ".join(rec.get("rationale", [])) + ". Tell me to accept, counter at a price, or stop."]
    if r.get("status") and r.get("negotiation_id"):
        current = r.get("current_offer") or {}
        return [f"Negotiation #{r['negotiation_id']} is {str(r['status']).lower()}"
                + (f"; the current offer is ₹{money_str(current.get('unit_price'))} for {current.get('quantity')}"
                   if current.get("unit_price") else "")
                + (". It's your turn to respond." if r.get("your_turn") else ".")]
    return [r["note"]] if r.get("note") else []


def _order(r: dict) -> list[str]:
    lines = [f"Order {r.get('order_number')} is {str(r.get('status', '')).replace('_', ' ')}: {r.get('quantity')} {r.get('unit')} "
             f"at ₹{money_str(r.get('unit_price'))}/{r.get('unit')}, total ₹{money_str(r.get('total_payable'))}."]
    if r.get("blocked"):
        lines.append(r["blocked"])
    if r.get("pickup_date"):
        lines.append(f"Pickup is planned for {r['pickup_date']}.")
    lines += [f"Next: {a}" for a in r.get("next_actions", [])]
    return lines


def compose(state: WorkflowState) -> tuple[str, list[str]]:
    results = state.get("agent_results") or {}
    lines, actions = [], []
    if (results.get("policy") or {}).get("refused"):
        lines.append(results["policy"]["reason"])
    if results.get("discovery"):
        lines += _discovery(results["discovery"])
        if results["discovery"].get("match_count"):
            actions.append("Ask me to make an offer on one of these listings.")
    if results.get("vendor_demand"):
        r = results["vendor_demand"]
        lines.append(f"{r['match_count']} buyer(s) are looking for this produce." if r["match_count"]
                     else "No open buyer requests match this produce right now.")
        for m in r["matches"][:5]:
            lines.append(f"- {m.get('vendor_name') or 'A vendor'}: " + "; ".join(m["reasons"]))
    if results.get("market"):
        m = results["market"]
        deals = m.get("negotiated_prices") or {}
        lines.append(f"{m.get('crop_name')}: median agreed price ₹{money_str(deals.get('median'))} over "
                     f"{deals.get('sample_size')} recent deals" if deals.get("median") is not None
                     else f"Not enough recent {m.get('crop_name')} deals for a price benchmark.")
        if m.get("note"):
            lines.append(m["note"])
    if results.get("negotiation"):
        lines += _negotiation(results["negotiation"])
    if results.get("quality"):
        q = results["quality"]
        if not q.get("usable"):
            lines.append("I couldn't get a usable assessment from the photo(s); a person should inspect the produce.")
        elif q.get("human_inspection_recommended"):
            lines.append("The photo assessment is uncertain; a human inspection is recommended.")
    if results.get("listing"):
        r = results["listing"]
        if r.get("created"):
            lines.append(f"Your listing #{r['listing_id']} is {r['status']}.")
        elif r.get("blocked") or r.get("failed"):
            lines.append(f"The listing wasn't created: {r.get('blocked') or r.get('failed')}.")
        lines += r.get("notes", [])
    if results.get("order"):
        lines += _order(results["order"])
    if results.get("delivery"):
        d = results["delivery"]
        route = d.get("route_estimate")
        lines.append("Delivery options: " + ", ".join(o["description"] for o in d.get("options", [])) + ".")
        lines.append(f"Estimated {route['distance_km']} km, about {route['duration_minutes']} minutes. {route['note']}"
                     if route else d.get("note", ""))
    if results.get("logistics"):
        r = results["logistics"]
        lines.append(f"Done: {r['action'].replace('_', ' ')} for order #{r['order_id']}." if not r.get("failed")
                     else f"That didn't go through: {r['failed']}")
    if results.get("dispute"):
        r = results["dispute"]
        if r.get("resolved"):
            lines.append(f"Dispute #{r['dispute_id']} was {r['status']} by an admin ({r['resolution_type'].replace('_', ' ')}).")
        elif r.get("resolution_failed"):
            lines.append(f"The resolution couldn't be recorded: {r['resolution_failed']}")
        else:
            lines.append(f"I prepared an evidence report for dispute #{r['dispute_id']} (severity {r['severity']}) and "
                         "sent it to an admin, who decides the outcome.")
            if r.get("missing_evidence"):
                lines.append("Evidence that would help: " + "; ".join(r["missing_evidence"]))
    if results.get("admin"):
        a = results["admin"]
        lines.append(f"Last {a['period_days']} days: {len(a['flagged_listings'])} flagged listing(s), "
                     f"{len(a['open_disputes'])} open dispute(s), {len(a['workflow_issues'])} failed/escalated workflow(s), "
                     f"{a['pending_admin_approvals']} decision(s) waiting for an admin.")
    if results.get("approval"):
        r = results["approval"]
        lines.append(f"Nothing was done: the {str(r.get('action', '')).replace('_', ' ')} request was {r.get('status')}.")
    for error in state.get("errors") or []:
        if error.get("tool") and error.get("status", 500) >= 400 and error.get("message"):
            lines.append(f"({error['tool'].replace('_', ' ')}: {error['message']})")
    if not lines:
        lines.append("I can help you find produce or buyers, negotiate offers, create listings from photos, track "
                     "orders and pickups, and investigate disputes. What would you like to do?")
    for note in state.get("uncertainty") or []:
        if note.startswith("still missing"):
            lines.append(f"I need more detail to continue ({note}).")
    return "\n".join(line for line in lines if line), actions


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip("0").rstrip(".") for n in _NUMBER.findall(text or "")}


async def respond(state: WorkflowState, runtime: Runtime[RunContext]) -> dict:
    ctx = runtime.context
    message, actions = compose(state)
    source = "rules"
    facts = {"agent_results": state.get("agent_results") or {}, "draft_message": message}
    if settings().llm_responses and ctx.llm and ctx.llm.can_serve(TaskType.SUMMARIZATION, structured=True) \
            and state.get("understanding_source") == "llm":
        try:
            parsed, response = await ctx.llm.structured(
                TaskType.SUMMARIZATION, FinalAnswer,
                [Message.user("Rewrite draft_message as a short, clear reply to the user. Use only facts below; "
                              "do not add numbers, prices, promises or advice that isn't there.\n"
                              + json.dumps(facts, default=str)[:12000])],
                system="You write replies for an agricultural marketplace assistant. " + UNTRUSTED_DATA_RULES,
                run_id=ctx.run_id, user_id=ctx.user_id,
            )
            if _numbers(parsed.message) <= _numbers(json.dumps(facts, default=str)):
                message, source = parsed.message, f"model:{response.model_id}"
        except LLMError:
            pass
    return {
        "response": {
            "message": message, "suggested_actions": actions, "source": source,
            "facts": state.get("agent_results") or {},
            "security_flags": state.get("security_flags") or [],
            "limits": list(NEVER_AUTOMATED),
        },
        "messages": [{"role": "assistant", "content": message}],
        "status": "completed",
    }
