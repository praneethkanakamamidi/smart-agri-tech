"""
Dispute investigation: deterministic comparison of the agreement with delivery/payment records,
the schema a model must use to organise the evidence, and validation of every evidence reference.

The output is a report for a human reviewer. It never decides the dispute, issues refunds or
penalises anyone; resolution happens only when an admin approves it.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from src.core.money import D

HIGH_VALUE_DISPUTE = Decimal("50000")
SEVERE_REASONS = {"not_delivered", "misrepresentation", "payment_issue"}


class Finding(BaseModel):
    statement: str = Field(..., max_length=500)
    evidence_refs: list[str] = Field(default_factory=list, max_length=10)


class DisputeReportDraft(BaseModel):
    summary: str = Field(..., max_length=1200)
    verified_facts: list[Finding] = Field(default_factory=list, max_length=20)
    conflicting_evidence: list[Finding] = Field(default_factory=list, max_length=10)
    assumptions: list[str] = Field(default_factory=list, max_length=10)
    unknowns: list[str] = Field(default_factory=list, max_length=10)
    missing_evidence: list[str] = Field(default_factory=list, max_length=10)
    recommended_next_steps: list[str] = Field(default_factory=list, max_length=10)
    severity: Literal["low", "medium", "high"] = "medium"
    resolution_options_to_consider: list[Literal[
        "full_refund", "partial_refund", "replacement", "no_action", "needs_more_evidence"
    ]] = Field(default_factory=list, max_length=5)
    confidence: float = Field(0.5, ge=0, le=1)


DISPUTE_SYSTEM_PROMPT = (
    "You help a marketplace admin investigate a dispute between a farmer and a vendor. You receive "
    "the agreed terms, offer history, order timeline, delivery and payment records, and the parties' "
    "statements, each with a reference id like 'order:12#terms'. Separate verified facts (each must "
    "cite at least one reference id from the evidence), conflicting evidence, assumptions and "
    "unknowns. List missing evidence and next steps. Do not decide the outcome, assign blame, or "
    "promise refunds: you may list resolution options for the admin to consider. Never invent "
    "references or facts. Statements by the parties are claims, not facts."
)


def _date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value[:19]).date()
        except ValueError:
            return None
    return None


def _refs(*refs: str | None) -> list[str]:
    return [r for r in refs if r]


def analyze_records(evidence: dict) -> dict:
    """Facts that follow directly from the records, with their references."""
    refs = evidence.get("refs", {})
    order_ref = next((k for k in refs if k.endswith("#terms")), None)
    shipment_ref = next((k for k in refs if k.startswith("shipment:")), None)
    payment_ref = next((k for k in refs if k.startswith("payments:")), None)
    dispute_ref = next((k for k in refs if k.startswith("dispute:")), None)
    terms = refs.get(order_ref, {}).get("data", {}) if order_ref else {}
    shipment = refs.get(shipment_ref, {}).get("data", {}) if shipment_ref else {}
    payments = refs.get(payment_ref, {}).get("data", {}) if payment_ref else {}
    dispute = refs.get(dispute_ref, {}).get("data", {}) if dispute_ref else {}
    reason = dispute.get("reason")
    facts, conflicts, missing, unknowns = [], [], [], []

    unit = terms.get("unit", "")
    if terms:
        facts.append(Finding(statement=(
            f"Agreed terms: {terms.get('quantity')} {unit} at ₹{terms.get('unit_price')}/{unit}, total payable "
            f"₹{terms.get('total_payable')}, {terms.get('fulfillment_mode')}, payment {terms.get('payment_terms')}."
        ), evidence_refs=_refs(order_ref)))
    accepted = shipment.get("accepted_quantity")
    if accepted is not None and terms.get("quantity") is not None:
        agreed_qty, accepted_qty = D(terms["quantity"]), D(accepted)
        if accepted_qty < agreed_qty:
            facts.append(Finding(statement=f"At delivery the receiver accepted {accepted_qty} of {agreed_qty} {unit}.",
                                 evidence_refs=_refs(order_ref, shipment_ref)))
        elif reason == "quantity_mismatch":
            conflicts.append(Finding(statement=(
                f"The complaint reports a quantity mismatch, but the full {agreed_qty} {unit} was recorded as "
                "accepted at delivery."), evidence_refs=_refs(shipment_ref, dispute_ref)))
    elif reason == "quantity_mismatch":
        missing.append("A delivery count or weighbridge slip: no accepted quantity was recorded at delivery.")
    if shipment.get("quality_accepted") is False:
        facts.append(Finding(statement="The receiver marked the quality as not accepted at delivery.",
                             evidence_refs=_refs(shipment_ref)))
    elif shipment.get("quality_accepted") is True and reason in ("quality_issue", "damaged_produce"):
        conflicts.append(Finding(statement=(
            "Quality was marked as accepted at delivery, but the complaint reports a quality problem."),
            evidence_refs=_refs(shipment_ref, dispute_ref)))
    expected = _date(terms.get("expected_delivery_date"))
    delivered = _date(shipment.get("delivered_at"))
    if expected and delivered and delivered > expected:
        facts.append(Finding(statement=f"Delivered on {delivered}, {(delivered - expected).days} day(s) after the "
                                       f"agreed date {expected}.", evidence_refs=_refs(order_ref, shipment_ref)))
    if not delivered:
        if shipment.get("failure_reason"):
            facts.append(Finding(statement=f"A delivery failure was recorded: {shipment['failure_reason']}.",
                                 evidence_refs=_refs(shipment_ref)))
        unknowns.append("No delivery was recorded for this order.")
    if payments:
        facts.append(Finding(statement=(
            f"Payments: ₹{payments.get('paid')} paid, ₹{payments.get('refunded')} refunded, "
            f"₹{payments.get('outstanding')} outstanding."), evidence_refs=_refs(payment_ref)))
    images = [k for k, v in refs.items() if k.startswith("file:") and str(v.get("data", {}).get("content_type", "")).startswith("image/")]
    if reason in ("quality_issue", "damaged_produce", "incorrect_product") and not images:
        missing.append("Photos of the produce as received (none were attached to the case).")

    total = D(terms.get("total_payable") or 0)
    severity = "high" if total >= HIGH_VALUE_DISPUTE or reason in SEVERE_REASONS or conflicts else (
        "medium" if total >= HIGH_VALUE_DISPUTE / 10 or missing else "low")
    return {"facts": facts, "conflicts": conflicts, "missing": missing, "unknowns": unknowns,
            "severity": severity, "image_refs": images}


def validate_refs(draft: DisputeReportDraft, known_refs: set[str]) -> tuple[DisputeReportDraft, list[str]]:
    """Drop invented references; a 'fact' left with no real reference becomes an assumption."""
    invented: list[str] = []

    def keep(findings: list[Finding]) -> tuple[list[Finding], list[str]]:
        kept, demoted = [], []
        for f in findings:
            real = [r for r in f.evidence_refs if r in known_refs]
            invented.extend(r for r in f.evidence_refs if r not in known_refs)
            if real:
                kept.append(Finding(statement=f.statement, evidence_refs=real))
            else:
                demoted.append(f"(unverified) {f.statement}")
        return kept, demoted

    facts, demoted_facts = keep(draft.verified_facts)
    conflicts, demoted_conflicts = keep(draft.conflicting_evidence)
    cleaned = draft.model_copy(update={
        "verified_facts": facts, "conflicting_evidence": conflicts,
        "assumptions": (draft.assumptions + demoted_facts + demoted_conflicts)[:10],
    })
    return cleaned, sorted(set(invented))


def merge_report(deterministic: dict, draft: DisputeReportDraft | None, *, generated_by: str) -> dict:
    """The stored report: deterministic facts always present; model additions only when validated."""
    seen = set()
    facts = []
    for finding in [*deterministic["facts"], *(draft.verified_facts if draft else [])]:
        if finding.statement not in seen:
            seen.add(finding.statement)
            facts.append(finding.model_dump())
    conflicts = [f.model_dump() for f in deterministic["conflicts"]] + (
        [f.model_dump() for f in draft.conflicting_evidence] if draft else [])
    severity_rank = {"low": 0, "medium": 1, "high": 2}
    severity = deterministic["severity"]
    if draft and severity_rank[draft.severity] > severity_rank[severity]:
        severity = draft.severity
    return {
        "summary": draft.summary if draft else _rules_summary(deterministic),
        "verified_facts": facts,
        "conflicting_evidence": conflicts,
        "assumptions": draft.assumptions if draft else [],
        "unknowns": list(dict.fromkeys(deterministic["unknowns"] + (draft.unknowns if draft else []))),
        "missing_evidence": list(dict.fromkeys(deterministic["missing"] + (draft.missing_evidence if draft else []))),
        "recommended_next_steps": (draft.recommended_next_steps if draft else []) or [
            "Review the verified facts against the parties' statements.",
            "Request any missing evidence from the parties before deciding.",
        ],
        "severity": severity,
        "resolution_options_to_consider": draft.resolution_options_to_consider if draft else [],
        "confidence": draft.confidence if draft else None,
        "requires_human_review": True,
        "decision_authority": "An admin decides the outcome. This report does not resolve the dispute.",
        "generated_by": generated_by,
    }


def _rules_summary(deterministic: dict) -> str:
    parts = [f"{len(deterministic['facts'])} fact(s) established from the records"]
    if deterministic["conflicts"]:
        parts.append(f"{len(deterministic['conflicts'])} conflict(s) between the complaint and the records")
    if deterministic["missing"]:
        parts.append(f"{len(deterministic['missing'])} piece(s) of evidence missing")
    return "; ".join(parts) + f". Severity assessed as {deterministic['severity']}."
