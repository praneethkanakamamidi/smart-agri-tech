"""
The workflow graph.

    START -> understand ─┬─> clarify ─(interrupt: input)─> understand
                         ├─> discovery ──> negotiation_prepare? ─> await_approval
                         ├─> vendor_demand / market_insight / negotiation_status / admin_oversight
                         ├─> analyze_images ─> prepare_listing ─> await_approval ─> create_listing_execute
                         ├─> negotiation_prepare ─> await_approval ─(interrupt: approval)─> negotiation_execute
                         │       negotiation_execute ─> await_counterparty ─(interrupt: external)─> negotiation_review
                         │       negotiation_review ─> await_approval | order_logistics | respond
                         ├─> order_logistics ─> await_approval ─> logistics_execute
                         └─> dispute_investigate ─> await_approval (admin queue) ─> dispute_resolve_execute
    every path ends in respond -> END

One flat graph rather than nested subgraphs: every interrupt lives in one checkpoint namespace,
which keeps resume, inspection and the runner simple. Specialist boundaries are the node
modules and the explicit transition allow-list below; a node can only hand off to its listed
successors, so a model can't send the workflow anywhere irrelevant or round in circles (and
AGENT_MAX_STEPS bounds every run).
"""
from langgraph.graph import END, START, StateGraph

from src.agents.context import RunContext
from src.agents.nodes.common import EXECUTE_NODE
from src.agents.nodes.discovery import discovery, market_insight, vendor_demand
from src.agents.nodes.disputes import admin_oversight, dispute_investigate, dispute_resolve_execute
from src.agents.nodes.listing import analyze_images, create_listing_execute, prepare_listing
from src.agents.nodes.logistics import logistics_execute, order_logistics
from src.agents.nodes.negotiation import (
    await_counterparty, negotiation_execute, negotiation_prepare, negotiation_review, negotiation_status,
)
from src.agents.nodes.respond import respond
from src.agents.nodes.supervisor import await_approval, clarify, understand
from src.agents.state import WorkflowState
from src.helpers.logging_config import get_logger

logger = get_logger("agents.graph")

SPECIALISTS = {"discovery", "vendor_demand", "market_insight", "negotiation_prepare", "negotiation_status",
               "analyze_images", "prepare_listing", "order_logistics", "dispute_investigate", "admin_oversight"}

NODES = {
    "understand": understand, "clarify": clarify, "await_approval": await_approval,
    "discovery": discovery, "vendor_demand": vendor_demand, "market_insight": market_insight,
    "negotiation_prepare": negotiation_prepare, "negotiation_execute": negotiation_execute,
    "await_counterparty": await_counterparty, "negotiation_review": negotiation_review,
    "negotiation_status": negotiation_status, "analyze_images": analyze_images, "prepare_listing": prepare_listing,
    "create_listing_execute": create_listing_execute, "order_logistics": order_logistics,
    "logistics_execute": logistics_execute, "dispute_investigate": dispute_investigate,
    "dispute_resolve_execute": dispute_resolve_execute, "admin_oversight": admin_oversight, "respond": respond,
}

TRANSITIONS: dict[str, set[str]] = {
    "understand": SPECIALISTS | {"clarify", "respond"},
    "clarify": {"understand"},
    "await_approval": set(EXECUTE_NODE.values()) | {"respond"},
    "discovery": {"negotiation_prepare", "respond"},
    "vendor_demand": {"respond"},
    "market_insight": {"respond"},
    "negotiation_status": {"respond"},
    "admin_oversight": {"respond"},
    "negotiation_prepare": {"await_approval", "clarify", "respond"},
    "negotiation_execute": {"await_counterparty", "order_logistics", "respond"},
    "await_counterparty": {"negotiation_review"},
    "negotiation_review": {"await_approval", "await_counterparty", "order_logistics", "respond"},
    "analyze_images": {"prepare_listing", "respond"},
    "prepare_listing": {"await_approval", "clarify", "respond"},
    "create_listing_execute": {"respond"},
    "order_logistics": {"await_approval", "respond"},
    "logistics_execute": {"respond"},
    "dispute_investigate": {"await_approval", "respond"},
    "dispute_resolve_execute": {"respond"},
}


def _router(source: str):
    allowed = TRANSITIONS[source]

    def route(state: WorkflowState) -> str:
        target = state.get("next") or "respond"
        if target not in allowed:
            logger.warning(f"blocked transition {source} -> {target}; ending the workflow")
            return "respond"
        return target

    route.__name__ = f"route_from_{source}"
    return route


def build_graph(checkpointer=None):
    graph = StateGraph(WorkflowState, context_schema=RunContext)
    for name, fn in NODES.items():
        graph.add_node(name, fn)
    graph.add_edge(START, "understand")
    for source, targets in TRANSITIONS.items():
        graph.add_conditional_edges(source, _router(source), {t: t for t in targets})
    graph.add_edge("respond", END)
    return graph.compile(checkpointer=checkpointer, name="farmbridge")
