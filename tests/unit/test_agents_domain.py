"""Deterministic agent logic: pricing, ranking, quality claims, dispute evidence, request understanding."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.agents.domain.disputes import DisputeReportDraft, Finding, analyze_records, merge_report, validate_refs
from src.agents.domain.pricing import MarketBand, farmer_response, opening_offer, validate_terms, vendor_response
from src.agents.domain.quality import (
    MANDATORY_LIMITATIONS, ProduceQualityAssessment, postprocess, suggested_listing_fields,
)
from src.agents.domain.understanding import RequestUnderstanding, build_plan, missing_for, rules_understanding
from src.agents.nodes.negotiation import message_consistent
from src.agents.retrieval.catalog import match_terms
from src.agents.retrieval.ranking import Candidate, RankingRequest, rank, rrf

D = Decimal
RELIABLE = MarketBand(p25=D("20"), median=D("22"), p75=D("24"), sample_size=12, reliable=True)


# ---- pricing -----------------------------------------------------------------------------------------

def test_opening_offer_uses_target_but_never_above_max_or_asking():
    assert opening_offer(D("25"), RELIABLE, target=D("21"), max_price=None).unit_price == D("21.00")
    assert opening_offer(D("25"), RELIABLE, target=D("30"), max_price=D("26")).unit_price == D("25.00")
    assert opening_offer(D("25"), RELIABLE, target=None, max_price=D("19")).unit_price == D("19.00")


def test_opening_offer_uses_market_band_only_when_reliable():
    assert opening_offer(D("25"), RELIABLE, target=None, max_price=None).unit_price == D("20.00")
    unreliable = MarketBand(p25=D("10"), sample_size=2, reliable=False)
    assert opening_offer(D("25"), unreliable, target=None, max_price=None).unit_price == D("23.00")


def test_vendor_accepts_within_authority_and_counters_monotonically():
    assert vendor_response(D("24"), D("21"), max_price=D("25"), band=MarketBand(), round_no=2, max_rounds=5).action == "accept"
    counter = vendor_response(D("28"), D("21"), max_price=D("25"), band=MarketBand(), round_no=2, max_rounds=5)
    assert counter.action == "counter" and D("21") < counter.unit_price <= D("25")


def test_vendor_escalates_without_authority_or_after_max_rounds():
    assert vendor_response(D("28"), D("21"), max_price=None, band=MarketBand(), round_no=2, max_rounds=5).action == "escalate"
    assert vendor_response(D("28"), D("21"), max_price=D("25"), band=MarketBand(), round_no=5, max_rounds=5).action == "escalate"


def test_farmer_counter_never_goes_below_private_floor():
    decision = farmer_response(D("15"), D("25"), None, floor=D("22"), band=MarketBand(), round_no=1, max_rounds=5)
    assert decision.action == "counter" and decision.unit_price >= D("22")
    near = farmer_response(D("24.5"), D("25"), None, floor=D("22"), band=MarketBand(), round_no=1, max_rounds=5)
    assert near.action == "accept"


def test_validate_terms_reports_every_violation():
    problems = validate_terms(unit_price=D("30"), quantity=D("600"), available=D("500"), min_order=D("50"),
                              max_price=D("25"))
    assert any("available" in p for p in problems) and any("authorised maximum" in p for p in problems)
    assert validate_terms(unit_price=D("20"), quantity=D("100"), available=D("500"), min_order=D("50")) == []


def test_drafted_messages_must_quote_the_computed_price():
    assert message_consistent("Can you do ₹23/kg?", D("23"))
    assert not message_consistent("How about Rs 21 per kg", D("23"))
    assert message_consistent("Looking forward to working together", D("23"))


# ---- ranking -------------------------------------------------------------------------------------------

def cand(listing_id, price, qty, distance, **kw):
    return Candidate(listing_id=listing_id, farmer_id=listing_id * 10, crop_id=1, crop_name="Tomato", unit="kg",
                     asking_price=D(price), available_qty=D(qty), distance_km=distance, relevance=kw.pop("relevance", 1.0), **kw)


def test_rrf_rewards_agreement_between_retrievers():
    scores = rrf([[1, 2, 3], [2, 1, 4]])
    assert scores[1] == scores[2] > scores[3] > 0 and 4 in scores


def test_rank_orders_by_explainable_business_score():
    weights = {"relevance": 0.35, "price": 0.2, "distance": 0.15, "quantity": 0.15, "trust": 0.1, "freshness": 0.05}
    request = RankingRequest(quantity=D("100"), max_price=D("25"), radius_km=100)
    ranked = rank([cand(1, "30", "500", 90), cand(2, "22", "500", 10), cand(3, "22", "50", 10)], request, weights)
    assert [c.listing_id for c in ranked][0] == 2
    reasons = " ".join(ranked[0].reasons)
    assert "₹22" in reasons and "10.0 km" in reasons and "full 100 kg" in reasons
    partial = next(c for c in ranked if c.listing_id == 3)
    assert any("partial" in r for r in partial.reasons)


def test_rank_only_reorders_given_candidates():
    weights = {"relevance": 1}
    ranked = rank([cand(1, "20", "10", None)], RankingRequest(), weights)
    assert [c.listing_id for c in ranked] == [1] and "distance unknown" in " ".join(ranked[0].reasons)


# ---- quality -----------------------------------------------------------------------------------------------

def assessment(**kw):
    base = dict(image_usable=True, commodity_guess="tomato", commodity_confidence=0.9, overall_confidence=0.8,
                observations=[{"attribute": "colour", "observation": "uniform deep red", "confidence": 0.9},
                              {"attribute": "surface", "observation": "pesticide free and safe to eat", "confidence": 0.5}],
                apparent_defects=[{"type": "bruising", "severity": "minor", "estimated_share_percent": 5,
                                   "evidence": "two fruits show soft dark patches"}],
                packaging_observed="crates", visual_grade_estimate="A")
    base.update(kw)
    return ProduceQualityAssessment.model_validate(base)


def test_postprocess_strips_unsupported_claims_and_adds_limitations():
    result = postprocess(assessment())
    assert all("pesticide" not in o["observation"] for o in result["observations"])
    assert result["unsupported_claims_removed"] and result["recommend_human_inspection"] is True
    assert all(limit in result["limitations"] for limit in MANDATORY_LIMITATIONS)
    assert result["grade_label"] == "visual estimate - not a certified grade"


def test_low_confidence_or_severe_defects_need_inspection():
    assert postprocess(assessment(observations=[], overall_confidence=0.4))["recommend_human_inspection"]
    severe = [{"type": "rot", "severity": "severe", "evidence": "black soft areas"}]
    assert postprocess(assessment(observations=[], apparent_defects=severe))["recommend_human_inspection"]


def test_photo_suggestions_never_include_quantity_or_price():
    suggestions = suggested_listing_fields(postprocess(assessment(observations=[])))
    assert {"quantity", "asking_price", "unit"}.isdisjoint(suggestions)
    assert suggestions["quality_grade"] == "A" and "visual estimate" in suggestions["quality_grade_basis"]


# ---- disputes --------------------------------------------------------------------------------------------------

def evidence(accepted="80", quality=False, reason="quality_issue", images=False):
    refs = {
        "order:5#terms": {"kind": "agreed_terms", "data": {"quantity": "100", "unit": "kg", "unit_price": "22",
                                                           "total_payable": "2200", "expected_delivery_date": "2026-10-01",
                                                           "fulfillment_mode": "pickup", "payment_terms": "pay_before_dispatch"}},
        "shipment:3": {"kind": "delivery_record", "data": {"accepted_quantity": accepted, "quality_accepted": quality,
                                                           "delivered_at": "2026-10-03T10:00:00"}},
        "dispute:9": {"kind": "complaint", "data": {"reason": reason, "description": "bad"}},
        "payments:5": {"kind": "payments", "data": {"paid": "2200", "refunded": "0", "outstanding": "0"}},
    }
    if images:
        refs["file:abc"] = {"kind": "uploaded_file", "data": {"content_type": "image/jpeg"}}
    return {"refs": refs}


def test_records_establish_facts_with_references():
    result = analyze_records(evidence())
    statements = " ".join(f.statement for f in result["facts"])
    assert "accepted 80 of 100 kg" in statements and "not accepted" in statements and "2 day(s) after" in statements
    assert all(f.evidence_refs for f in result["facts"])
    assert any("Photos" in m for m in result["missing"])


def test_conflicting_evidence_is_flagged_and_raises_severity():
    result = analyze_records(evidence(accepted="100", quality=True, images=True))
    assert result["conflicts"] and result["severity"] == "high"


def test_invented_references_are_removed_and_facts_demoted():
    draft = DisputeReportDraft(summary="s", verified_facts=[
        Finding(statement="real", evidence_refs=["shipment:3"]),
        Finding(statement="made up", evidence_refs=["order:999#terms"]),
    ])
    cleaned, invented = validate_refs(draft, set(evidence()["refs"]))
    assert [f.statement for f in cleaned.verified_facts] == ["real"]
    assert invented == ["order:999#terms"] and any("made up" in a for a in cleaned.assumptions)
    report = merge_report(analyze_records(evidence()), cleaned, generated_by="m")
    assert report["requires_human_review"] is True and "admin decides" in report["decision_authority"]


# ---- understanding & catalogue ---------------------------------------------------------------------------------

def test_rules_understanding_extracts_intent_constraints_and_references():
    u = rules_understanding("make an offer for 500 kg tomato under ₹25 per kg within 50 km",
                            {"order_quantity": 500, "unit": "kg", "max_price": 25}, ["Tomato"])
    assert u.intent == "make_offer" and u.quantity == 500 and u.max_price_per_unit == 25 and u.radius_km == 50
    assert build_plan(u, has_images=False) == ["discovery", "negotiation_prepare"]
    pickup = rules_understanding("schedule pickup for order 42 tomorrow", {}, [])
    assert pickup.intent == "schedule_pickup" and pickup.order_id == 42
    assert pickup.pickup_date == date.today() + timedelta(days=1) and not pickup.missing_information


def test_missing_information_produces_a_question():
    u = RequestUnderstanding(intent="confirm_order", confidence=0.9)
    assert missing_for(u)[0][0] == "order_id"


@pytest.mark.parametrize("term,expected", [
    ("tomatoes", "Tomato"), ("tamatar", "Tomato"), ("టమాటా", "Tomato"), ("pyaz", "Onion"), ("Onion", "Onion"),
])
def test_commodity_matching(term, expected):
    crops = [(1, "Tomato", "టమాటా"), (2, "Onion", None), (3, "Rice", None)]
    assert match_terms([term], crops)[0]["crop_name"] == expected


def test_unknown_commodities_are_not_invented():
    assert match_terms(["dragonfruit"], [(1, "Tomato", None)]) == []
