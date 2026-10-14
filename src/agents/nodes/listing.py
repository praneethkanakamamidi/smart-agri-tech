"""
Image-assisted listing creation.

  analyze_images         -> vision assessment per photo (structured, post-validated)
  prepare_listing        -> merge what the farmer said with what the photos suggest into a draft;
                            quantity and price come only from the farmer, never from a photo
  await_approval         -> the farmer reviews/edits every field, then approves
  create_listing_execute -> ListingsService.create with the approved draft (same validation as the API)
"""
from langgraph.runtime import Runtime

from src.agents.config import settings
from src.agents.domain.quality import suggested_listing_fields
from src.agents.nodes.common import advance, call, enter, last_user_text, money_str, propose, tool_error, understanding
from src.agents.state import WorkflowState
from src.agents.tools.base import ToolError
from src.agents.context import RunContext

LISTING_EDITABLE = ["crop", "variety", "quantity", "unit", "asking_price", "min_acceptable_price", "min_order_qty",
                    "quality_grade", "harvest_date", "available_until", "packaging", "description", "delivery_options",
                    "publish"]


async def analyze_images(state: WorkflowState, runtime: Runtime[RunContext]) -> dict:
    updates = enter(state, "analyze_images")
    u = understanding(state)
    assessments, errors = [], []
    for file_id in (state.get("file_ids") or [])[: settings().vision_max_images]:
        try:
            assessments.append(await call(runtime, "analyze_images", "analyze_produce_image", {
                "file_id": file_id, "commodity_hint": u.commodity_terms[0] if u.commodity_terms else None}))
        except ToolError as e:
            errors.append(tool_error("analyze_images", "analyze_produce_image", e))
    usable = [a for a in assessments if a.get("analysis_available") and a.get("image_usable")]
    best = max(usable, key=lambda a: a.get("overall_confidence") or 0) if usable else None
    summary = {
        "analysed": len(assessments), "usable": len(usable),
        "best": best, "all": [{k: a.get(k) for k in ("file_id", "analysis_available", "image_usable",
                                                       "commodity_guess", "visual_grade_estimate", "overall_confidence",
                                                       "recommend_human_inspection", "reason")} for a in assessments],
        "human_inspection_recommended": any(a.get("recommend_human_inspection") for a in assessments) or not usable,
    }
    return advance(state, {**updates, "agent_results": {"quality": summary}, **({"errors": errors} if errors else {})})


async def prepare_listing(state: WorkflowState, runtime: Runtime[RunContext]) -> dict:
    updates = enter(state, "prepare_listing")
    u = understanding(state)
    quality = (state.get("agent_results") or {}).get("quality") or {}
    suggestions = suggested_listing_fields(quality["best"]) if quality.get("best") else {}
    notes = []

    terms = list(u.commodity_terms)
    photo_guess = suggestions.get("commodity_guess")
    if not terms and photo_guess:
        terms = [photo_guess]
        notes.append(f"Produce taken from the photo ({photo_guess}); confirm it.")
    crop = None
    try:
        if terms:
            matches = (await call(runtime, "prepare_listing", "resolve_commodity", {"terms": terms[:3]}))["matches"]
            crop = matches[0] if matches else None
    except ToolError as e:
        updates["errors"] = [tool_error("prepare_listing", "resolve_commodity", e)]
    if crop and photo_guess and u.commodity_terms and photo_guess.lower() not in crop["crop_name"].lower():
        notes.append(f"The photo looks like {photo_guess}, but you said {crop['crop_name']}; your word is used.")

    missing = []
    if not crop:
        missing.append("which produce this is (it must be in the catalogue)")
    if not u.quantity:
        missing.append("the quantity with its unit")
    if not (u.target_price_per_unit or u.max_price_per_unit or u.min_price_per_unit):
        missing.append("your asking price per unit")
    if missing:
        if (state.get("clarifications") or 0) < 3:
            return {**updates, "pending_question": "To draft the listing I still need " + ", ".join(missing) + ".",
                    "next": "clarify"}
        return {**updates, "agent_results": {"listing": {"blocked": "missing: " + ", ".join(missing)}}, "next": "respond"}

    asking = u.target_price_per_unit or u.max_price_per_unit or u.min_price_per_unit
    draft = {
        "crop": crop["crop_id"], "variety": suggestions.get("variety"), "quantity": u.quantity,
        "unit": u.unit or "kg", "asking_price": asking,
        "min_acceptable_price": u.min_price_per_unit if u.min_price_per_unit and u.min_price_per_unit < asking else None,
        "quality_grade": (u.quality_grades[0] if u.quality_grades else suggestions.get("quality_grade")),
        "packaging": suggestions.get("packaging"),
        "description": (last_user_text(state)[:250] + (" | Photo: " + suggestions["description"] if suggestions.get("description") else ""))[:500],
        "delivery_options": [u.delivery_option] if u.delivery_option else ["pickup"],
        "image_file_ids": list(state.get("file_ids") or [])[:10],
        "available_until": None, "publish": True,
    }
    if suggestions.get("quality_grade") and not u.quality_grades:
        notes.append("The grade is a visual estimate from the photo, not a certified grade. Change it if needed.")
    summary = (f"Publish a listing: {money_str(u.quantity)} {draft['unit']} of {crop['crop_name']} at "
               f"₹{money_str(asking)}/{draft['unit']}" + (f", grade {draft['quality_grade']}" if draft["quality_grade"] else "")
               + ". Review every field first.")
    try:
        proposal = await propose(
            runtime, "prepare_listing", action="create_listing", step_key="create_listing", payload=draft,
            summary=summary, editable_fields=[f for f in LISTING_EDITABLE if f in draft],
            context={"photo_assessment": quality.get("best"), "notes": notes,
                     "human_inspection_recommended": quality.get("human_inspection_recommended"),
                     "fields_from_photo": [k for k in ("variety", "packaging", "quality_grade") if suggestions.get(k)]},
        )
    except ToolError as e:
        return {**updates, "errors": [tool_error("prepare_listing", "request_human_approval", e)],
                "agent_results": {"listing": {"blocked": e.message}}, "next": "respond"}
    return {**updates, **proposal, "listing_draft": draft,
            "agent_results": {"listing": {"draft": draft, "notes": notes, "crop_name": crop["crop_name"]}}}


async def create_listing_execute(state: WorkflowState, runtime: Runtime[RunContext]) -> dict:
    updates = enter(state, "create_listing_execute")
    pending = state["pending_approval"]
    try:
        result = await call(runtime, "create_listing_execute", "create_listing", pending["payload"],
                            approval_id=pending["approval_id"])
    except ToolError as e:
        return {**updates, "errors": [tool_error("create_listing_execute", "create_listing", e)],
                "agent_results": {"listing": {"failed": e.message}}, "next": "respond"}
    return {**updates, "pending_approval": None,
            "agent_results": {"listing": {"created": True, "listing_id": result["listing_id"], "status": result["status"]}},
            "next": "respond"}
