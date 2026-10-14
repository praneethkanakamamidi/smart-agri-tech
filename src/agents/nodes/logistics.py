"""
Order and logistics specialist: status, confirmation, pickup scheduling, delivery estimates.
Proposes; the user approves; logistics_execute runs the approved tool. Delivery and completion
are never marked by an agent.
"""
from datetime import date

from langgraph.runtime import Runtime

from src.agents.context import RunContext
from src.agents.nodes.common import advance, call, enter, money_str, propose, tool_error, understanding
from src.agents.state import WorkflowState
from src.agents.tools.base import ToolError

SCHEDULABLE = ("pending_confirmation", "confirmed", "preparing", "ready_for_pickup", "delivery_failed")


def next_actions(status: dict) -> list[str]:
    s, role = status["status"], status["my_role"]
    payments = status.get("payments") or {}
    actions = []
    if status.get("awaiting_my_confirmation"):
        actions.append("Confirm the order terms.")
    if s == "confirmed" and role == "farmer":
        actions.append("Start preparing the order.")
    if s in SCHEDULABLE and not (status.get("shipment") or {}).get("pickup_date"):
        actions.append("Agree a pickup/delivery date.")
    if role == "vendor" and float(payments.get("outstanding") or 0) > 0 and s not in ("cancelled", "refunded"):
        actions.append(f"₹{money_str(payments['outstanding'])} is outstanding under {status.get('payment_terms')} terms.")
    if s == "delivered" and role == "vendor":
        actions.append("Check the produce and mark the order complete, or raise a dispute within the dispute window.")
    return actions


async def order_logistics(state: WorkflowState, runtime: Runtime[RunContext]) -> dict:
    updates = enter(state, "order_logistics")
    u = understanding(state)
    order_id = u.order_id or (state.get("order") or {}).get("order_id")
    if not order_id:
        return advance(state, {**updates, "uncertainty": ["no order number given"]})
    try:
        status = await call(runtime, "order_logistics", "get_order_status", {"order_id": order_id})
    except ToolError as e:
        return advance(state, {**updates, "errors": [tool_error("order_logistics", "get_order_status", e)]})
    summary = {k: status.get(k) for k in ("order_id", "order_number", "status", "produce", "quantity", "unit",
                                          "unit_price", "total_payable", "payment_terms", "fulfillment_mode",
                                          "expected_delivery_date", "awaiting_my_confirmation")}
    summary["pickup_date"] = (status.get("shipment") or {}).get("pickup_date")
    summary["next_actions"] = next_actions(status)
    results = {"order": summary}
    updates["order"] = {"order_id": order_id, "order_number": status["order_number"], "status": status["status"]}
    intent = state.get("intent")

    try:
        if intent == "delivery_options":
            results["delivery"] = await call(runtime, "order_logistics", "get_delivery_options", {"order_id": order_id})
            return advance(state, {**updates, "agent_results": results})
        if intent == "schedule_pickup" and u.pickup_date:
            if status["status"] not in SCHEDULABLE:
                results["order"]["blocked"] = f"A pickup can't be scheduled while the order is {status['status']}."
                return advance(state, {**updates, "agent_results": results})
            if u.pickup_date < date.today():
                results["order"]["blocked"] = "The pickup date is in the past."
                return advance(state, {**updates, "agent_results": results})
            estimate = await call(runtime, "order_logistics", "get_delivery_options", {"order_id": order_id})
            return {**updates, "agent_results": results, **await propose(
                runtime, "order_logistics", action="schedule_pickup",
                step_key=f"pickup:{order_id}:{u.pickup_date.isoformat()}",
                payload={"order_id": order_id, "pickup_date": u.pickup_date.isoformat()},
                summary=(f"Schedule the pickup for order {status['order_number']} on {u.pickup_date.isoformat()}. "
                         "The other party is notified; no vehicle is booked."),
                editable_fields=["pickup_date", "window_start", "window_end", "pickup_address", "pickup_instructions"],
                context={"route_estimate": estimate.get("route_estimate"), "current_status": status["status"]},
            )}
        if status.get("awaiting_my_confirmation") and intent in (
                "confirm_order", "make_offer", "respond_to_offer", "find_supply", "negotiation_status"):
            return {**updates, "agent_results": results, **await propose(
                runtime, "order_logistics", action="confirm_order", step_key=f"confirm:{order_id}",
                payload={"order_id": order_id},
                summary=(f"Confirm order {status['order_number']}: {status['quantity']} {status['unit']} at "
                         f"₹{status['unit_price']}/{status['unit']}, total ₹{status['total_payable']}, "
                         f"{status['payment_terms']} payment, {status['fulfillment_mode']}."),
                editable_fields=[], context={"payments": status.get("payments")},
            )}
    except ToolError as e:
        return advance(state, {**updates, "agent_results": results,
                               "errors": [tool_error("order_logistics", "propose", e)]})
    return advance(state, {**updates, "agent_results": results})


async def logistics_execute(state: WorkflowState, runtime: Runtime[RunContext]) -> dict:
    updates = enter(state, "logistics_execute")
    pending = state["pending_approval"]
    try:
        result = await call(runtime, "logistics_execute", pending["action"], pending["payload"],
                            approval_id=pending["approval_id"])
    except ToolError as e:
        return {**updates, "errors": [tool_error("logistics_execute", pending["action"], e)],
                "agent_results": {"logistics": {"failed": e.message}}, "next": "respond"}
    done = {"action": pending["action"], "order_id": pending["payload"].get("order_id"),
            "status": result.get("status"), "pickup_date": pending["payload"].get("pickup_date"),
            "note": result.get("note") or result.get("success")}
    return {**updates, "pending_approval": None, "agent_results": {"logistics": done}, "next": "respond"}
