"""Discovery specialists: supplier search, buyer demand, market prices."""
from langgraph.runtime import Runtime

from src.agents.context import RunContext
from src.agents.nodes.common import advance, call, enter, last_user_text, tool_error, understanding
from src.agents.state import WorkflowState
from src.agents.tools.base import ToolError

MIN_SHOWN = 1


def _compact(match: dict) -> dict:
    keys = ("listing_id", "farmer_id", "crop_name", "variety", "asking_price", "unit", "available_quantity",
            "quality_grade", "distance_km", "score", "reasons", "district", "delivery_options")
    return {k: match.get(k) for k in keys}


async def discovery(state: WorkflowState, runtime: Runtime[RunContext]) -> dict:
    updates = enter(state, "discovery")
    u = understanding(state)
    args = {
        "query": u.semantic_query or last_user_text(state)[:300], "commodity_terms": u.commodity_terms,
        "quantity": u.quantity, "unit": u.unit, "max_price": u.max_price_per_unit,
        "target_price": u.target_price_per_unit, "quality_grades": u.quality_grades,
        "available_by": u.needed_by.isoformat() if u.needed_by else None, "delivery_option": u.delivery_option,
        "radius_km": u.radius_km, "limit": 10,
    }
    try:
        result = await call(runtime, "discovery", "search_listings", args)
        partial = False
        if not result["matches"] and u.quantity:
            # Nobody can fill the whole quantity: show who can fill part of it (clearly marked).
            result = await call(runtime, "discovery", "search_listings", {**args, "allow_partial": True})
            partial = bool(result["matches"])
    except ToolError as e:
        return advance(state, {**updates, "errors": [tool_error("discovery", "search_listings", e)], "plan": []})

    matches = [_compact(m) for m in result["matches"]]
    updates["candidate_matches"] = matches
    updates["agent_results"] = {"discovery": {
        "match_count": len(matches), "partial_matches_only": partial, "matches": matches[:5],
        "applied_filters": result["applied_filters"], "notes": result.get("notes", []),
        "resolved_commodities": result.get("resolved_commodities", []), "stats": result["stats"],
    }}
    plan = list(state.get("plan") or [])
    if plan and plan[0] == "negotiation_prepare":
        if not matches:
            plan = []  # nothing to negotiate on
        elif not state.get("selected_listing_id"):
            updates["selected_listing_id"] = matches[0]["listing_id"]
            updates["uncertainty"] = ["the top-ranked listing was chosen for the offer; you approve before anything is sent"]
    return advance(state, {**updates, "plan": plan})


async def vendor_demand(state: WorkflowState, runtime: Runtime[RunContext]) -> dict:
    updates = enter(state, "vendor_demand")
    u = understanding(state)
    try:
        result = await call(runtime, "vendor_demand", "search_vendor_demand", {
            "listing_id": u.listing_id, "commodity_terms": u.commodity_terms,
            "asking_price": u.min_price_per_unit or u.target_price_per_unit, "quantity": u.quantity,
            "radius_km": u.radius_km, "limit": 10,
        })
    except ToolError as e:
        return advance(state, {**updates, "errors": [tool_error("vendor_demand", "search_vendor_demand", e)]})
    return advance(state, {**updates, "agent_results": {"vendor_demand": {
        "match_count": len(result["matches"]), "matches": result["matches"][:10],
        "resolved_commodities": result.get("resolved_commodities", []),
    }}})


async def market_insight(state: WorkflowState, runtime: Runtime[RunContext]) -> dict:
    updates = enter(state, "market_insight")
    u = understanding(state)
    if not u.commodity_terms:
        return advance(state, {**updates, "uncertainty": ["no produce named for the price lookup"]})
    try:
        insights = await call(runtime, "market_insight", "retrieve_market_price_data",
                              {"commodity": u.commodity_terms[0], "unit": u.unit, "days": 30})
    except ToolError as e:
        return advance(state, {**updates, "errors": [tool_error("market_insight", "retrieve_market_price_data", e)]})
    return advance(state, {**updates, "agent_results": {"market": {
        "crop_name": insights.get("crop_name"), "negotiated_prices": insights.get("negotiated_prices"),
        "asking_prices": insights.get("asking_prices"), "note": insights.get("note"),
        "data_source": insights.get("data_source"),
    }}})
