"""
Dispute investigation specialist.

  dispute_investigate     -> gather authorised evidence, compare it with the agreement
                             deterministically, analyse evidence photos, let a model organise the
                             findings (every reference validated), store the report, then queue it
                             for an admin
  await_approval          -> (supervisor) waits for an admin decision (run status: escalated)
  dispute_resolve_execute -> resolve_dispute with the deciding admin's authority
"""
import json

from langgraph.runtime import Runtime

from src.agents.config import settings
from src.agents.context import RunContext
from src.agents.domain.disputes import (
    DISPUTE_SYSTEM_PROMPT, DisputeReportDraft, analyze_records, merge_report, validate_refs,
)
from src.agents.llm import Message, TaskType
from src.agents.llm.errors import LLMError
from src.agents.nodes.common import call, ctx_of, enter, propose, tool_error, understanding
from src.agents.policy import UNTRUSTED_DATA_RULES, wrap_untrusted
from src.agents.state import WorkflowState
from src.agents.tools.base import ToolError

RESOLUTION_PLACEHOLDER = "Admin to write the resolution before approving."
UNTRUSTED_KINDS = {"complaint", "message", "evidence", "status_change", "internal_note"}


def _evidence_for_model(refs: dict) -> str:
    """Records as JSON; free text written by the parties is wrapped as untrusted data."""
    trusted, untrusted = {}, []
    for ref, item in refs.items():
        data = dict(item.get("data") or {}) if isinstance(item.get("data"), dict) else item.get("data")
        if item.get("kind") in UNTRUSTED_KINDS and isinstance(data, dict):
            for field in ("description", "body"):
                if data.get(field):
                    untrusted.append(wrap_untrusted(f"{ref}.{field}", str(data.pop(field))[:1500]))
        trusted[ref] = {"kind": item.get("kind"), "data": data}
    return ("Records (reference id -> record):\n" + json.dumps(trusted, default=str)[:24000]
            + "\n\nStatements by the parties (claims, not facts):\n" + "\n".join(untrusted)[:12000])


async def dispute_investigate(state: WorkflowState, runtime: Runtime[RunContext]) -> dict:
    updates = enter(state, "dispute_investigate")
    ctx = ctx_of(runtime, "dispute_investigate")
    u = understanding(state)
    dispute_id = u.dispute_id or (state.get("dispute") or {}).get("dispute_id")
    try:
        evidence = await call(runtime, "dispute_investigate", "retrieve_evidence", {"dispute_id": dispute_id})
    except ToolError as e:
        return {**updates, "errors": [tool_error("dispute_investigate", "retrieve_evidence", e)], "next": "respond"}
    refs = evidence["refs"]
    deterministic = analyze_records(evidence)

    observations = {}
    for ref in deterministic["image_refs"][: settings().vision_max_images]:
        try:
            result = await call(runtime, "dispute_investigate", "analyze_produce_image", {"file_id": ref.split(":", 1)[1]})
            observations[f"analysis:{ref}"] = {"kind": "image_analysis_model_output", "data": {
                k: result.get(k) for k in ("analysis_available", "image_usable", "apparent_defects", "visual_grade_estimate",
                                           "overall_confidence", "limitations", "recommend_human_inspection")}}
        except ToolError:
            continue
    all_refs = {**refs, **observations}

    draft, generated_by, invented = None, "rules", []
    if ctx.llm and ctx.llm.can_serve(TaskType.DISPUTE_ANALYSIS, structured=True):
        try:
            draft, response = await ctx.llm.structured(
                TaskType.DISPUTE_ANALYSIS, DisputeReportDraft,
                [Message.user(f"Dispute #{dispute_id} (reason: {evidence['reason']}).\n\n" + _evidence_for_model(all_refs))],
                system=DISPUTE_SYSTEM_PROMPT + "\n\n" + UNTRUSTED_DATA_RULES, run_id=ctx.run_id, user_id=ctx.user_id,
            )
            draft, invented = validate_refs(draft, set(all_refs))
            generated_by = response.model_id
        except LLMError as e:
            updates["errors"] = [{"node": "dispute_investigate", "code": e.code, "message": "model unavailable; rules report"}]
    report = merge_report(deterministic, draft, generated_by=generated_by)
    report["invented_references_removed"] = invented
    report["image_observations"] = observations
    evidence_index = {ref: {"kind": item.get("kind")} for ref, item in all_refs.items()}
    try:
        saved = await call(runtime, "dispute_investigate", "create_dispute_report", {
            "dispute_id": dispute_id, "report": report, "evidence_index": evidence_index, "generated_by": generated_by})
        proposal = await propose(
            runtime, "dispute_investigate", action="resolve_dispute", step_key=f"resolve:{dispute_id}",
            payload={"dispute_id": dispute_id, "report_id": saved["report_id"], "status": "resolved",
                     "resolution": RESOLUTION_PLACEHOLDER, "resolution_type": "no_action", "refund_amount": None},
            summary=(f"Review the investigation of dispute #{dispute_id} (severity {report['severity']}) and record a "
                     "decision. Nothing happens until an admin writes and approves the resolution."),
            editable_fields=["status", "resolution", "resolution_type", "refund_amount"],
            context={"report_id": saved["report_id"], "severity": report["severity"],
                     "missing_evidence": report["missing_evidence"], "options": report["resolution_options_to_consider"]},
            requested_for_role="admin",
        )
    except ToolError as e:
        return {**updates, "errors": [tool_error("dispute_investigate", "report", e)], "next": "respond"}
    return {**updates, **proposal, "dispute": {"dispute_id": dispute_id, "report_id": saved["report_id"]},
            "evidence_refs": sorted(all_refs)[:40],
            "agent_results": {"dispute": {
                "dispute_id": dispute_id, "report_id": saved["report_id"], "severity": report["severity"],
                "verified_facts": len(report["verified_facts"]), "conflicts": len(report["conflicting_evidence"]),
                "missing_evidence": report["missing_evidence"], "generated_by": generated_by,
                "invented_references_removed": len(invented), "queued_for_admin": True,
            }}}


async def dispute_resolve_execute(state: WorkflowState, runtime: Runtime[RunContext]) -> dict:
    updates = enter(state, "dispute_resolve_execute")
    pending = state["pending_approval"]
    try:
        result = await call(runtime, "dispute_resolve_execute", "resolve_dispute", pending["payload"],
                            approval_id=pending["approval_id"])
    except ToolError as e:
        return {**updates, "errors": [tool_error("dispute_resolve_execute", "resolve_dispute", e)],
                "agent_results": {"dispute": {"resolution_failed": e.message}}, "next": "respond"}
    return {**updates, "pending_approval": None, "agent_results": {"dispute": {
        "resolved": True, "dispute_id": pending["payload"]["dispute_id"], "status": pending["payload"]["status"],
        "resolution_type": pending["payload"]["resolution_type"], "refund_id": result.get("refund_id"),
    }}, "next": "respond"}


async def admin_oversight(state: WorkflowState, runtime: Runtime[RunContext]) -> dict:
    updates = enter(state, "admin_oversight")
    try:
        overview = await call(runtime, "admin_oversight", "admin_overview", {"days": 7})
    except ToolError as e:
        return {**updates, "errors": [tool_error("admin_oversight", "admin_overview", e)], "next": "respond"}
    return {**updates, "agent_results": {"admin": overview}, "next": "respond"}
