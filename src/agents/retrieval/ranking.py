"""
Pure ranking functions for supplier matching.

Order of operations (enforced by search.py): hard SQL filters (status, stock, minimum order,
commodity, grade, dates, radius, blocks) -> lexical + semantic retrieval over survivors ->
reciprocal rank fusion -> optional cross-encoder -> this business score -> availability re-check.
Nothing here can resurrect a candidate the hard filters removed.

Every component is in [0, 1] and every reason quotes the actual value it was computed from.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass
class Candidate:
    listing_id: int
    farmer_id: int
    crop_id: int
    crop_name: str
    unit: str
    asking_price: Decimal
    available_qty: Decimal
    min_order_qty: Decimal | None = None
    quality_grade: str | None = None
    variety: str | None = None
    distance_km: float | None = None
    farmer_verified: bool = False
    farmer_rating: float | None = None
    farmer_review_count: int = 0
    completed_orders: int = 0
    harvest_date: date | None = None
    availability_date: date | None = None
    organic_verified: bool = False
    delivery_options: list[str] = field(default_factory=list)
    district: str | None = None
    lexical_score: float = 0.0
    semantic_score: float | None = None  # cosine similarity, None if the listing isn't indexed yet
    rerank_score: float | None = None
    relevance: float = 0.0
    score: float = 0.0
    components: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


@dataclass
class RankingRequest:
    quantity: Decimal | None = None
    max_price: Decimal | None = None
    target_price: Decimal | None = None
    radius_km: float | None = None
    today: date = field(default_factory=date.today)


def rrf(rankings: list[list[int]], k: int = 60) -> dict[int, float]:
    """Reciprocal rank fusion: robust to the very different scales of ts_rank and cosine similarity."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for position, item in enumerate(ranking):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + position + 1)
    return scores


def normalise(scores: dict[int, float]) -> dict[int, float]:
    if not scores:
        return {}
    top = max(scores.values())
    return {k: (v / top if top > 0 else 0.0) for k, v in scores.items()}


def price_fit(asking: Decimal, max_price: Decimal | None, target: Decimal | None) -> float:
    reference = target or max_price
    if reference is None or reference <= 0:
        return 0.5  # neutral: no budget given
    ratio = float(asking / reference)
    if ratio <= 1:
        return min(1.0, 0.75 + 0.25 * (1 - ratio) / 0.3)  # cheaper than budget scores higher, capped
    return max(0.0, 1 - (ratio - 1) / 0.3)  # 30% over budget -> 0


def distance_fit(distance_km: float | None, radius_km: float | None) -> float:
    if distance_km is None:
        return 0.4  # unknown location ranks below known nearby suppliers
    radius = radius_km or 100.0
    return max(0.0, 1 - distance_km / radius) if radius > 0 else 0.0


def quantity_fit(available: Decimal, requested: Decimal | None) -> float:
    if not requested or requested <= 0:
        return 0.5
    return 1.0 if available >= requested else float(available / requested)


def trust_fit(verified: bool, rating: float | None, reviews: int, completed: int) -> float:
    score = 0.4 if verified else 0.0
    if rating is not None and reviews >= 3:
        score += 0.4 * max(0.0, (rating - 1) / 4)
    score += 0.2 * min(1.0, completed / 20)
    return min(1.0, score)


def freshness_fit(harvest: date | None, today: date) -> float:
    if harvest is None:
        return 0.5
    age = (today - harvest).days
    if age < 0:
        return 0.6  # pre-harvest: not available yet but bookable
    return max(0.0, 1 - age / 30)


def score_candidate(c: Candidate, request: RankingRequest, weights: dict[str, float]) -> Candidate:
    components = {
        "relevance": c.relevance,
        "price": price_fit(c.asking_price, request.max_price, request.target_price),
        "distance": distance_fit(c.distance_km, request.radius_km),
        "quantity": quantity_fit(c.available_qty, request.quantity),
        "trust": trust_fit(c.farmer_verified, c.farmer_rating, c.farmer_review_count, c.completed_orders),
        "freshness": freshness_fit(c.harvest_date, request.today),
    }
    total_weight = sum(weights.get(k, 0) for k in components) or 1.0
    c.components = {k: round(v, 4) for k, v in components.items()}
    c.score = round(sum(components[k] * weights.get(k, 0) for k in components) / total_weight, 4)
    c.reasons = explain(c, request)
    return c


def explain(c: Candidate, request: RankingRequest) -> list[str]:
    reasons = [f"{c.crop_name}{f' ({c.variety})' if c.variety else ''}: {c.available_qty} {c.unit} available "
               f"at an asking price of ₹{c.asking_price}/{c.unit}"]
    if request.quantity:
        if c.available_qty >= request.quantity:
            reasons.append(f"can fill your full {request.quantity} {c.unit}")
        else:
            reasons.append(f"can supply {c.available_qty} of your {request.quantity} {c.unit} (partial)")
    if c.min_order_qty:
        reasons.append(f"minimum order {c.min_order_qty} {c.unit}")
    budget = request.target_price or request.max_price
    if budget:
        diff = c.asking_price - budget
        reasons.append(f"asking price is ₹{abs(diff)} {'above' if diff > 0 else 'below' if diff < 0 else 'equal to'} "
                       f"your ₹{budget}/{c.unit}" + (" (negotiable)" if diff > 0 else ""))
    if c.distance_km is not None:
        reasons.append(f"{c.distance_km:.1f} km away (straight-line)")
    else:
        reasons.append("distance unknown (no location on file)")
    if c.quality_grade:
        reasons.append(f"farmer-declared grade {c.quality_grade}")
    if c.farmer_verified:
        reasons.append("verified farmer")
    if c.farmer_rating is not None and c.farmer_review_count >= 3:
        reasons.append(f"rated {c.farmer_rating:.1f}/5 from {c.farmer_review_count} reviews")
    if c.completed_orders:
        reasons.append(f"{c.completed_orders} completed orders")
    if c.organic_verified:
        reasons.append("organic certificate verified by the platform")
    if c.semantic_score is not None and c.semantic_score >= 0.5:
        reasons.append("description closely matches your request")
    return reasons


def rank(candidates: list[Candidate], request: RankingRequest, weights: dict[str, float]) -> list[Candidate]:
    scored = [score_candidate(c, request, weights) for c in candidates]
    return sorted(scored, key=lambda c: (-c.score, c.asking_price, c.listing_id))
