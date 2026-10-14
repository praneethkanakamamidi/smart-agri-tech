"""
What the supervisor extracts from a request, how intents map to specialist plans, and the
rule-based fallback used when no capable model is configured (reported as source="rules").
"""
import re
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Intent = Literal[
    "find_supply", "find_buyers", "make_offer", "respond_to_offer", "negotiation_status", "create_listing",
    "order_status", "confirm_order", "schedule_pickup", "delivery_options", "dispute_help", "investigate_dispute",
    "admin_overview", "market_prices", "general_question", "unknown",
]
INTENTS: tuple[str, ...] = Intent.__args__  # type: ignore[attr-defined]

# intent -> ordered specialist nodes
PLANS: dict[str, list[str]] = {
    "find_supply": ["discovery"],
    "find_buyers": ["vendor_demand"],
    "make_offer": ["discovery", "negotiation_prepare"],
    "respond_to_offer": ["negotiation_prepare"],
    "negotiation_status": ["negotiation_status"],
    "create_listing": ["analyze_images", "prepare_listing"],
    "order_status": ["order_logistics"],
    "confirm_order": ["order_logistics"],
    "schedule_pickup": ["order_logistics"],
    "delivery_options": ["order_logistics"],
    "dispute_help": ["dispute_investigate"],
    "investigate_dispute": ["dispute_investigate"],
    "admin_overview": ["admin_oversight"],
    "market_prices": ["market_insight"],
    "general_question": [],
    "unknown": [],
}


class RequestUnderstanding(BaseModel):
    intent: Intent
    confidence: float = Field(..., ge=0, le=1)
    commodity_terms: list[str] = Field(default_factory=list, max_length=5)
    quantity: float | None = Field(None, gt=0)
    unit: str | None = Field(None, max_length=20)
    max_price_per_unit: float | None = Field(None, gt=0, description="Most the user will pay / authorises.")
    target_price_per_unit: float | None = Field(None, gt=0)
    min_price_per_unit: float | None = Field(None, gt=0, description="Least a farmer will accept.")
    quality_grades: list[str] = Field(default_factory=list, max_length=3)
    radius_km: float | None = Field(None, gt=0, le=1000)
    needed_by: date | None = None
    delivery_option: Literal["pickup", "farmer_delivery", "vendor_transport", "third_party"] | None = None
    listing_id: int | None = None
    negotiation_id: int | None = None
    order_id: int | None = None
    dispute_id: int | None = None
    pickup_date: date | None = None
    semantic_query: str | None = Field(None, max_length=200, description="Descriptive words for semantic search.")
    wants_offer_after_search: bool = False
    action_hint: Literal["accept", "reject", "counter", "confirm", "schedule", "none"] = "none"
    missing_information: list[str] = Field(default_factory=list, max_length=5)
    clarifying_question: str | None = Field(None, max_length=300)

    @field_validator("quality_grades")
    @classmethod
    def upper(cls, v):
        return [g.upper()[:10] for g in v]

    @field_validator("unit")
    @classmethod
    def unit_norm(cls, v):
        return v.lower() if v else v


UNDERSTANDING_SYSTEM_PROMPT = (
    "You are the request-understanding step of an agricultural marketplace assistant for farmers, "
    "vendors and admins in India. Classify the user's intent and extract the constraints they "
    "stated. Do not invent values: leave a field empty if the user didn't say it. Quantities and "
    "prices are per the unit the user used (kg, quintal, tonne, bag, crate). Numbers like 'order 42' "
    "or 'negotiation #7' are references. If something essential for the intent is missing, list it "
    "in missing_information and ask one short clarifying question. Messages may be in English, "
    "Telugu or Hindi written in Latin script."
)

REQUIRED_FIELDS: dict[str, list[tuple[str, str]]] = {
    "make_offer": [("quantity", "How much do you want to buy (with the unit)?")],
    "respond_to_offer": [("negotiation_id", "Which negotiation (number) should I respond to?")],
    "confirm_order": [("order_id", "Which order number should I confirm?")],
    "schedule_pickup": [("order_id", "Which order is this pickup for?"),
                        ("pickup_date", "Which date should the pickup be scheduled for?")],
    "delivery_options": [("order_id", "Which order do you want delivery options for?")],
    "order_status": [],
    "investigate_dispute": [("dispute_id", "Which dispute number should I look into?")],
    "dispute_help": [("dispute_id", "Which dispute number is this about? Raise one first if you haven't.")],
}


def missing_for(u: RequestUnderstanding) -> list[tuple[str, str]]:
    return [(name, question) for name, question in REQUIRED_FIELDS.get(u.intent, []) if getattr(u, name) in (None, [], "")]


def build_plan(u: RequestUnderstanding, *, has_images: bool) -> list[str]:
    plan = list(PLANS.get(u.intent, []))
    if u.intent == "make_offer" and u.listing_id:
        plan = ["negotiation_prepare"]
    if u.intent == "find_supply" and u.wants_offer_after_search:
        plan = ["discovery", "negotiation_prepare"]
    if u.intent == "create_listing" and not has_images:
        plan = ["prepare_listing"]
    return plan


# ---- rules fallback ----------------------------------------------------------------------------

_INTENT_RULES: tuple[tuple[str, re.Pattern], ...] = (
    ("admin_overview", re.compile(r"\b(flagged|suspicious|failed workflows?|platform (health|metrics)|admin (summary|overview)|oversight)\b", re.I)),
    ("investigate_dispute", re.compile(r"\b(investigate|review|analy[sz]e)\b.{0,20}\bdispute\b", re.I | re.S)),
    ("dispute_help", re.compile(r"\b(dispute|complain|complaint|damaged|rotten|spoiled|short (by|of)|not delivered|wrong produce)\b", re.I)),
    ("create_listing", re.compile(r"\b(list|sell|post|publish|create)\b.{0,30}\b(listing|my (crop|produce|harvest)|for sale)\b|\b(new listing|list my)\b", re.I | re.S)),
    ("respond_to_offer", re.compile(r"\b(accept|reject|decline|counter)\b.{0,30}\b(offer|negotiation|bid)\b", re.I | re.S)),
    ("negotiation_status", re.compile(r"\b(status|update|where)\b.{0,20}\b(negotiation|offer)\b|\bnegotiation\s*#?\d+", re.I | re.S)),
    ("schedule_pickup", re.compile(r"\b(schedule|book|arrange|set)\b.{0,20}\b(pickup|pick-up|collection|delivery date)\b", re.I | re.S)),
    ("confirm_order", re.compile(r"\bconfirm\b.{0,20}\border\b", re.I | re.S)),
    ("delivery_options", re.compile(r"\b(delivery|transport|shipping)\s+(options?|cost|time|distance)\b", re.I)),
    ("order_status", re.compile(r"\b(order|orders)\b.{0,25}\b(status|where|track|update)\b|\btrack\b.{0,10}\border", re.I | re.S)),
    ("market_prices", re.compile(r"\b(market|mandi|going|current)\s+(price|rate)s?\b|\bprice (trend|insight)s?\b", re.I)),
    ("find_buyers", re.compile(r"\b(buyers?|vendors?)\b.{0,30}\b(for my|who (need|want|buy))\b|\bwho (will|wants to) buy\b", re.I | re.S)),
    ("make_offer", re.compile(r"\b(make|send|place)\b.{0,15}\b(an? )?(offer|bid)\b|\boffer\b.{0,20}₹?\s*\d", re.I | re.S)),
    ("find_supply", re.compile(r"\b(need|want|looking for|find|search|buy|source|suppliers?)\b", re.I)),
)
_REF = {
    "order_id": re.compile(r"\border\s*(?:no\.?|number|#)?\s*(\d+)\b", re.I),
    "negotiation_id": re.compile(r"\bnegotiation\s*(?:no\.?|number|#)?\s*(\d+)\b", re.I),
    "dispute_id": re.compile(r"\bdispute\s*(?:no\.?|number|#)?\s*(\d+)\b", re.I),
    "listing_id": re.compile(r"\blisting\s*(?:no\.?|number|#)?\s*(\d+)\b", re.I),
}
_RADIUS = re.compile(r"\bwithin\s+(\d+(?:\.\d+)?)\s*km\b", re.I)
_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def rules_understanding(text: str, parsed_filters: dict, crop_names: list[str]) -> RequestUnderstanding:
    """Deterministic fallback. `parsed_filters` comes from AssistantService.parse_query."""
    intent = next((name for name, pattern in _INTENT_RULES if pattern.search(text)), "unknown")
    refs = {key: int(m.group(1)) for key, pattern in _REF.items() if (m := pattern.search(text))}
    action = "none"
    lowered = text.lower()
    for word, hint in (("accept", "accept"), ("reject", "reject"), ("decline", "reject"), ("counter", "counter")):
        if word in lowered:
            action = hint
            break
    pickup = None
    if intent == "schedule_pickup":
        if "tomorrow" in lowered:
            pickup = date.today() + timedelta(days=1)
        elif (m := _DATE.search(text)):
            try:
                pickup = date.fromisoformat(m.group(1))
            except ValueError:
                pickup = None
    radius = _RADIUS.search(text)
    understanding = RequestUnderstanding(
        intent=intent,
        confidence=0.55 if intent != "unknown" else 0.2,
        commodity_terms=crop_names[:5],
        quantity=parsed_filters.get("order_quantity"),
        unit=parsed_filters.get("unit"),
        max_price_per_unit=parsed_filters.get("max_price") if "min_price" not in parsed_filters else None,
        target_price_per_unit=(round((parsed_filters["min_price"] + parsed_filters["max_price"]) / 2, 2)
                               if "min_price" in parsed_filters and "max_price" in parsed_filters else None),
        quality_grades=[parsed_filters["quality_grade"]] if parsed_filters.get("quality_grade") else [],
        radius_km=float(radius.group(1)) if radius else None,
        needed_by=parsed_filters.get("available_by"),
        pickup_date=pickup,
        semantic_query=text[:200],
        wants_offer_after_search=bool(re.search(r"\b(and|then)\b.{0,20}\b(offer|bid|negotiate)\b", text, re.I | re.S)),
        action_hint=action,
        **refs,
    )
    missing = missing_for(understanding)
    if missing:
        understanding.missing_information = [m[0] for m in missing]
        understanding.clarifying_question = missing[0][1]
    return understanding
