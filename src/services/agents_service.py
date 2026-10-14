"""
API-facing service for the agent layer: starting and continuing workflows, approvals, run
history, direct tool endpoints and admin oversight. Execution itself is the runner's job.

Authorization here is ownership of runs and approvals. Conversation history is context only: a
message saying "I'm the admin" or "approve this" changes nothing, because roles come from the
account and approvals only from the approval endpoint.
"""
import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.config import settings
from src.agents.context import RunContext
from src.agents.limits import check_workflow_start
from src.agents.llm import get_router
from src.agents.llm.errors import LLMError, NoCapableModel
from src.agents.retrieval.embeddings import get_embedder
from src.agents.runner import RunNotResumable
from src.agents.runtime import runtime
from src.agents.tools.approvals import approval_view
from src.agents.tools.base import ToolError, canonical, payload_hash, validate_args
from src.core.audit import audit
from src.core.storage import storage
from src.data_models.agents_model import (
    AgentApprovalRequests, AgentModelCalls, AgentToolCalls, AgentWorkflowEvents, AgentWorkflowRuns,
    APPROVAL_APPROVED, APPROVAL_PENDING, APPROVAL_REJECTED, AWAITING_APPROVAL, AWAITING_INPUT, COMPLETED,
    DisputeInvestigationReports, ESCALATED, FAILED, QUEUED, RUNNING, TOOL_DENIED,
)
from src.data_models.platform_model import StoredFiles
from src.data_models.users_model import Users
from src.helpers.serializers import model_to_dict
from src.security_utils.role_guard import ADMIN, FARMER
from src.services.disputes_service import DisputesService
from src.services.files_service import FilesService

PLACEHOLDER_RESOLUTION = "Admin to write the resolution before approving."


def _require_runtime():
    if not runtime.ready or runtime.runner is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"The assistant is unavailable right now ({runtime.error or 'starting'}).")
    return runtime.runner


def _pending_view(pending: dict | None) -> dict | None:
    if not pending:
        return None
    kind = pending.get("type")
    if kind == "input":
        return {"type": "input", "question": pending.get("question"), "missing": pending.get("missing", [])}
    if kind == "approval":
        return {"type": "approval", "approval_id": pending.get("approval_id"), "action": pending.get("action"),
                "summary": pending.get("summary"), "decided_by_role": pending.get("requested_for_role") or "you"}
    return {"type": "external", "summary": pending.get("summary"), "waiting_on": pending.get("waiting_on"),
            "negotiation_id": pending.get("negotiation_id")}


class AgentsService:
    # ---- views ---------------------------------------------------------------------------------

    async def _run(self, db: AsyncSession, run_id: str, user: Users, *, allow_admin: bool = True) -> AgentWorkflowRuns:
        run = await db.get(AgentWorkflowRuns, run_id)
        if not run or (run.user_id != user.id and not (allow_admin and user.role_name == ADMIN)):
            raise HTTPException(status_code=404, detail="Workflow not found.")
        return run

    async def run_view(self, db: AsyncSession, run: AgentWorkflowRuns) -> dict:
        approvals = (await db.execute(select(AgentApprovalRequests).where(AgentApprovalRequests.run_id == run.id)
                                      .order_by(AgentApprovalRequests.id))).scalars().all()
        result = run.result or {}
        return {
            "workflow_id": run.id, "conversation_id": run.conversation_id, "workflow_type": run.workflow_type,
            "intent": run.intent, "status": run.status, "current_node": run.current_node,
            "pending": _pending_view(run.pending), "response": result.get("response"),
            "error": run.error if run.status == FAILED else None, "attempts": run.attempts,
            "approvals": [{k: v for k, v in approval_view(a).items() if k != "run_id"} for a in approvals],
            "created_at": run.created_at, "updated_at": run.updated_at, "completed_at": run.completed_at,
        }

    async def _execute(self, run_id: str, background: bool) -> None:
        runner = _require_runtime()
        if background or not settings().inline_execution:
            if settings().inline_execution or settings().worker_enabled:
                runner.schedule(run_id)  # the worker would also pick it up; the lease prevents double runs
            return
        await runner.drive(run_id)

    async def _fresh(self, run_id: str, user: Users) -> dict:
        from src.db_connections.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            return await self.run_view(db, await self._run(db, run_id, user))

    # ---- starting / continuing -------------------------------------------------------------------

    async def _transcribe(self, db: AsyncSession, user: Users, file_id: str) -> str:
        await FilesService.require_owned(db, [file_id], user.id, {"voice_note"})
        f = (await db.execute(select(StoredFiles).where(StoredFiles.id == file_id))).scalar_one()
        if f.size_bytes > settings().audio_max_mb * 1024 * 1024:
            raise HTTPException(status_code=413, detail="The voice note is too long.")
        try:
            text, _ = await get_router().transcribe(storage.read(f.storage_path), f.content_type, user_id=user.id,
                                                    language=user.preferred_language or None)
        except NoCapableModel:
            raise HTTPException(status_code=422, detail="Voice input isn't available: no speech model is configured.")
        except LLMError as e:
            raise HTTPException(status_code=502, detail=f"Couldn't transcribe the voice note ({e.code}).")
        if not text.strip():
            raise HTTPException(status_code=422, detail="The voice note had no recognisable speech.")
        return text.strip()[:2000]

    async def _carry_over(self, db: AsyncSession, user: Users, conversation_id: str | None) -> dict:
        if not conversation_id:
            return {}
        last = (await db.execute(select(AgentWorkflowRuns).where(
            AgentWorkflowRuns.conversation_id == conversation_id, AgentWorkflowRuns.user_id == user.id,
            AgentWorkflowRuns.status == COMPLETED,
        ).order_by(AgentWorkflowRuns.created_at.desc()).limit(1))).scalar_one_or_none()
        if last is None:
            owner = (await db.execute(select(AgentWorkflowRuns.user_id).where(
                AgentWorkflowRuns.conversation_id == conversation_id).limit(1))).scalar_one_or_none()
            if owner is not None and owner != user.id:
                raise HTTPException(status_code=404, detail="Conversation not found.")
            return {}
        return (last.result or {}).get("carry_over") or {}

    async def chat(self, user: Users, payload, db: AsyncSession) -> tuple[dict, int]:
        runner = _require_runtime()
        if payload.workflow_id:
            run = await self._run(db, payload.workflow_id, user, allow_admin=False)
            if run.status == AWAITING_INPUT:
                text = payload.message or await self._transcribe(db, user, payload.voice_file_id)
                return await self.provide_input(user, run.id, text, db, background=payload.background), 200
            raise HTTPException(status_code=409, detail=f"That workflow is {run.status}; start a new message instead.")
        await check_workflow_start(user.id)
        text = payload.message or await self._transcribe(db, user, payload.voice_file_id)
        file_ids = await FilesService.require_owned(db, payload.file_ids, user.id, {"listing_image", "dispute_evidence"})
        carry_over = await self._carry_over(db, user, payload.conversation_id)
        purposes = set((await db.execute(select(StoredFiles.purpose).where(StoredFiles.id.in_(file_ids)))).scalars().all()) \
            if file_ids else set()
        # Listing photos from a farmer start the image-assisted listing workflow; anything else is a chat.
        workflow_type = "listing_intake" if purposes == {"listing_image"} and user.role_name == FARMER else "chat"
        run_id = await runner.create_run(
            user_id=user.id, role=user.role_name, message=text, workflow_type=workflow_type,
            conversation_id=payload.conversation_id or str(uuid.uuid4()), file_ids=file_ids, carry_over=carry_over,
        )
        await self._execute(run_id, payload.background)
        return await self._fresh(run_id, user), 202 if payload.background else 200

    async def listing_from_images(self, user: Users, payload, db: AsyncSession) -> tuple[dict, int]:
        runner = _require_runtime()
        await check_workflow_start(user.id)
        file_ids = await FilesService.require_owned(db, payload.file_ids, user.id, {"listing_image"})
        run_id = await runner.create_run(
            user_id=user.id, role=user.role_name, workflow_type="listing_intake", file_ids=file_ids,
            message=payload.notes or "Create a listing from these photos.",
        )
        await self._execute(run_id, payload.background)
        return await self._fresh(run_id, user), 202 if payload.background else 200

    async def investigate_dispute(self, user: Users, dispute_id: int, payload, db: AsyncSession) -> tuple[dict, int]:
        runner = _require_runtime()
        await check_workflow_start(user.id)
        await DisputesService().get(dispute_id, user.id, user.role_name == ADMIN, db)  # 404 unless party or admin
        run_id = await runner.create_run(
            user_id=user.id, role=user.role_name, workflow_type="dispute_investigation", dispute_id=dispute_id,
            message=f"Investigate dispute #{dispute_id}.",
        )
        await self._execute(run_id, payload.background)
        return await self._fresh(run_id, user), 202 if payload.background else 200

    async def provide_input(self, user: Users, run_id: str, text: str, db: AsyncSession, background: bool = False) -> dict:
        runner = _require_runtime()
        run = await self._run(db, run_id, user, allow_admin=False)
        if run.status != AWAITING_INPUT:
            raise HTTPException(status_code=409, detail=f"This workflow is {run.status}, not waiting for an answer.")
        await db.rollback()  # release the read before the runner locks the row
        try:
            await runner.queue_resume(run_id, {"type": "input", "text": text}, (AWAITING_INPUT,))
        except RunNotResumable as e:
            raise HTTPException(status_code=409, detail=str(e))
        await self._execute(run_id, background)
        return await self._fresh(run_id, user)

    async def cancel(self, user: Users, run_id: str) -> dict:
        try:
            await _require_runtime().cancel(run_id, user.id, is_admin=user.role_name == ADMIN)
        except RunNotResumable as e:
            raise HTTPException(status_code=409, detail=str(e))
        return await self._fresh(run_id, user)

    # ---- reads -----------------------------------------------------------------------------------

    async def get_run(self, user: Users, run_id: str, db: AsyncSession) -> dict:
        run = await self._run(db, run_id, user)
        if run.status == "waiting_external" and runtime.ready:
            await db.rollback()
            await runtime.runner.wake_external(run_id)  # pick up a counterparty reply without waiting for the worker
            return await self._fresh(run_id, user)
        return await self.run_view(db, run)

    async def list_runs(self, user: Users, db: AsyncSession, status_filter: str | None, page: int, page_size: int,
                        all_users: bool = False) -> dict:
        stmt = select(AgentWorkflowRuns)
        if not all_users:
            stmt = stmt.where(AgentWorkflowRuns.user_id == user.id)
        if status_filter:
            stmt = stmt.where(AgentWorkflowRuns.status == status_filter)
        total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar()
        rows = (await db.execute(stmt.order_by(AgentWorkflowRuns.updated_at.desc())
                                 .limit(page_size).offset((page - 1) * page_size))).scalars().all()
        return {"data": [{
            "workflow_id": r.id, "conversation_id": r.conversation_id, "workflow_type": r.workflow_type,
            "intent": r.intent, "status": r.status, "user_id": r.user_id if all_users else None,
            "pending": _pending_view(r.pending), "updated_at": r.updated_at, "created_at": r.created_at,
        } for r in rows], "page": page, "page_size": page_size, "total": total}

    async def events(self, user: Users, run_id: str, after_id: int | None, db: AsyncSession) -> dict:
        await self._run(db, run_id, user)
        stmt = select(AgentWorkflowEvents).where(AgentWorkflowEvents.run_id == run_id)
        if after_id:
            stmt = stmt.where(AgentWorkflowEvents.id > after_id)
        rows = (await db.execute(stmt.order_by(AgentWorkflowEvents.id).limit(500))).scalars().all()
        tools = (await db.execute(select(AgentToolCalls).where(AgentToolCalls.run_id == run_id)
                                  .order_by(AgentToolCalls.id).limit(500))).scalars().all()
        return {
            "events": [model_to_dict(e) for e in rows],
            "tool_calls": [{k: getattr(t, k) for k in ("id", "node", "tool", "kind", "status", "error_code",
                                                       "error_message", "latency_ms", "approval_id", "created_at")}
                           for t in tools],
        }

    # ---- approvals -----------------------------------------------------------------------------------

    def _may_decide(self, approval: AgentApprovalRequests, user: Users) -> bool:
        if approval.requested_for is not None:
            return approval.requested_for == user.id
        return approval.requested_for_role == user.role_name

    async def list_approvals(self, user: Users, db: AsyncSession, status_filter: str | None) -> list[dict]:
        stmt = select(AgentApprovalRequests).where(or_(
            AgentApprovalRequests.requested_for == user.id,
            and_(AgentApprovalRequests.requested_for.is_(None), AgentApprovalRequests.requested_for_role == user.role_name),
        ))
        stmt = stmt.where(AgentApprovalRequests.status == (status_filter or APPROVAL_PENDING))
        rows = (await db.execute(stmt.order_by(AgentApprovalRequests.created_at.desc()).limit(100))).scalars().all()
        return [approval_view(r) for r in rows]

    async def get_approval(self, user: Users, approval_id: int, db: AsyncSession) -> dict:
        approval = await db.get(AgentApprovalRequests, approval_id)
        if not approval or not self._may_decide(approval, user):
            raise HTTPException(status_code=404, detail="Approval not found.")
        return approval_view(approval)

    async def decide(self, user: Users, approval_id: int, payload, db: AsyncSession, request_ip: str | None = None) -> dict:
        runner = _require_runtime()
        approval = (await db.execute(select(AgentApprovalRequests).where(AgentApprovalRequests.id == approval_id)
                                     .with_for_update())).scalar_one_or_none()
        if not approval or not self._may_decide(approval, user):
            raise HTTPException(status_code=404, detail="Approval not found.")
        wanted = APPROVAL_APPROVED if payload.decision == "approve" else APPROVAL_REJECTED
        if approval.status != APPROVAL_PENDING:
            if approval.status == wanted and approval.reviewed_by == user.id:  # a retried request: same answer
                await db.rollback()
                return {"approval": approval_view(approval), "workflow": await self._fresh_for_approval(approval, user)}
            raise HTTPException(status_code=409, detail=f"This request is already {approval.status}.")
        if approval.expires_at and approval.expires_at < datetime.utcnow():
            raise HTTPException(status_code=409, detail="This request has expired.")
        run = await db.get(AgentWorkflowRuns, approval.run_id)
        if run.status not in (AWAITING_APPROVAL, ESCALATED, RUNNING, QUEUED):
            raise HTTPException(status_code=409, detail=f"The workflow is {run.status}.")

        before = approval.payload
        if wanted == APPROVAL_APPROVED:
            unknown = set(payload.edits) - set(approval.editable_fields or [])
            if unknown:
                raise HTTPException(status_code=422, detail=f"These fields can't be changed: {', '.join(sorted(unknown))}")
            try:
                merged = canonical(validate_args(approval.action, {**approval.payload, **payload.edits}))
            except ToolError as e:
                raise HTTPException(status_code=422, detail=e.message)
            if approval.action == "resolve_dispute" and merged.get("resolution") == PLACEHOLDER_RESOLUTION:
                raise HTTPException(status_code=422, detail="Write the resolution (edits.resolution) before approving.")
            approval.payload, approval.payload_hash = merged, payload_hash(merged)
        approval.status, approval.reviewed_by = wanted, user.id
        approval.decision_note, approval.decided_at = payload.note, datetime.utcnow()
        audit(db, f"agent.approval_{wanted}", "agent_approval", approval.id, actor_id=user.id, actor_role=user.role_name,
              before={"payload": before} if payload.edits else None,
              after={"action": approval.action, "edited_fields": sorted(payload.edits), "run_id": approval.run_id},
              ip_address=request_ip)
        await db.commit()

        if run.status in (AWAITING_APPROVAL, ESCALATED):
            try:
                await runner.queue_resume(run.id, {"approval_id": approval.id, "decision": wanted,
                                                   "payload": approval.payload, "note": payload.note},
                                          (AWAITING_APPROVAL, ESCALATED))
                await self._execute(run.id, background=False)
            except RunNotResumable:
                pass  # the run settles on its own and picks up the decision (see WorkflowRunner._settle)
        return {"approval": approval_view(approval), "workflow": await self._fresh_for_approval(approval, user)}

    async def _fresh_for_approval(self, approval: AgentApprovalRequests, user: Users) -> dict:
        from src.db_connections.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            run = await db.get(AgentWorkflowRuns, approval.run_id)
            view = await self.run_view(db, run)
        if run.user_id != user.id:  # an admin deciding another user's run sees the outcome, not the conversation
            view = {k: view[k] for k in ("workflow_id", "status", "pending", "approvals")}
        return view

    # ---- direct tools -----------------------------------------------------------------------------------

    def _direct_ctx(self, user: Users) -> RunContext:
        rt = runtime if runtime.ready else None
        from src.agents.tools.base import ToolExecutor

        return RunContext(run_id=None, user_id=user.id, role=user.role_name, correlation_id=uuid.uuid4().hex,
                          node="api", tools=rt.tools if rt else ToolExecutor(), llm=get_router())

    async def direct_tool(self, user: Users, tool: str, args: dict) -> dict:
        import src.agents.tools  # noqa: F401

        ctx = self._direct_ctx(user)
        try:
            return await ctx.tools.call(ctx, tool, args)
        except ToolError as e:
            raise HTTPException(status_code=e.status if 400 <= e.status < 600 else 400, detail=e.message)

    async def dispute_reports(self, user: Users, dispute_id: int, db: AsyncSession) -> list[dict]:
        is_admin = user.role_name == ADMIN
        await DisputesService().get(dispute_id, user.id, is_admin, db)
        rows = (await db.execute(select(DisputeInvestigationReports).where(
            DisputeInvestigationReports.dispute_id == dispute_id).order_by(DisputeInvestigationReports.created_at.desc())
        )).scalars().all()
        if is_admin:
            return [model_to_dict(r) for r in rows]
        # Parties see what they can act on, not the admin's working document.
        return [{"report_id": r.id, "status": r.status, "created_at": r.created_at,
                 "missing_evidence": (r.report or {}).get("missing_evidence", []),
                 "decision_authority": (r.report or {}).get("decision_authority")} for r in rows]

    # ---- admin ---------------------------------------------------------------------------------------------

    async def models_status(self, db: AsyncSession, days: int) -> dict:
        router = get_router()
        since = datetime.utcnow() - timedelta(days=days)
        usage = (await db.execute(
            select(AgentModelCalls.model_id, func.count(AgentModelCalls.id),
                   func.sum(case((AgentModelCalls.status != "ok", 1), else_=0)),
                   func.avg(AgentModelCalls.latency_ms), func.sum(AgentModelCalls.cost_usd),
                   func.sum(case((AgentModelCalls.fallback_rank > 0, 1), else_=0)))
            .where(AgentModelCalls.created_at >= since).group_by(AgentModelCalls.model_id)
        )).all()
        denied = (await db.execute(select(func.count(AgentToolCalls.id)).where(
            AgentToolCalls.status == TOOL_DENIED, AgentToolCalls.created_at >= since))).scalar()
        return {
            "models": [m.public_view() for m in router.registry.all()],
            "circuit_breakers": router.circuit.snapshot(),
            "task_routes": settings().task_routes,
            "usage": [{"model_id": m, "calls": n, "errors": int(e or 0), "avg_latency_ms": round(float(lat or 0)),
                       "cost_usd": float(c) if c is not None else None, "served_as_fallback": int(f or 0)}
                      for m, n, e, lat, c, f in usage],
            "denied_tool_calls": denied,
            "embedding_model": get_embedder().model_version,
            "runtime": {"ready": runtime.ready, "error": runtime.error},
        }

    async def admin_retry(self, run_id: str) -> dict:
        runner = _require_runtime()
        try:
            await runner.retry_failed(run_id)
        except RunNotResumable as e:
            raise HTTPException(status_code=409, detail=str(e))
        runner.schedule(run_id)
        return {"workflow_id": run_id, "status": "queued"}
