"""
Durable workflow execution.

A run is a row in agent_workflow_runs plus a LangGraph thread (thread_id = run id) whose state
is checkpointed in PostgreSQL after every step (durability="sync"). Execution is driven by
`drive(run_id)`, which first *claims* the run with a lease (UPDATE ... RETURNING), so only one
API process or worker drives a run at a time. Inline API calls and the background worker use
the same path.

- Interrupts pause a run: input -> awaiting_input, approval -> awaiting_approval (escalated for
  an admin queue), external -> waiting_external. The API stores the resume value on the row and
  re-queues it; the next drive resumes the graph with Command(resume=...).
- A crash mid-run leaves the lease to expire; the worker re-claims it and LangGraph continues
  from the last checkpoint. Side effects are idempotent (approval-bound idempotency keys), so
  re-executing a node can't duplicate an offer, an order or a pickup.
- Failures retry with backoff up to AGENT_MAX_ATTEMPTS, then the run is marked failed.
- Identity: every drive rebuilds the RunContext from the database (owner -> active user -> role).
"""
import asyncio
import os
import socket
import uuid
from datetime import timedelta

from langgraph.types import Command
from sqlalchemy import and_, or_, select, text, update

from src.agents.config import settings
from src.agents.context import RunContext
from src.agents.nodes.common import StepLimitReached
from src.agents.policy import PolicyViolation
from src.agents.redaction import redact
from src.agents.tools.base import ToolExecutor, load_actor
from src.data_models.agents_model import (
    AgentApprovalRequests, AgentWorkflowEvents, AgentWorkflowRuns, APPROVAL_EXPIRED, APPROVAL_PENDING,
    APPROVAL_SUPERSEDED, AWAITING_APPROVAL, AWAITING_INPUT, CANCELLED, COMPLETED, ESCALATED, FAILED, PAUSED_STATES,
    QUEUED, RUNNING, TERMINAL_STATES, WAITING_EXTERNAL,
)
from src.data_models.negotiation_model import Negotiations, Offers
from src.db_connections.database import AsyncSessionLocal
from src.helpers.logging_config import get_logger
from src.core.clock import utcnow

logger = get_logger("agents.runner")


class RunNotResumable(Exception):
    pass


def _carry_over(state: dict) -> dict:
    """What the next run in the conversation may reuse: ids and short summaries only."""
    return {
        "understanding": state.get("understanding"),
        "candidate_matches": (state.get("candidate_matches") or [])[:10],
        "selected_listing_id": state.get("selected_listing_id"),
        "negotiation": state.get("negotiation"), "order": state.get("order"), "dispute": state.get("dispute"),
    }


class WorkflowRunner:
    def __init__(self, graph, tools: ToolExecutor, llm_provider, session_factory=AsyncSessionLocal):
        self.graph = graph
        self.tools = tools
        self.llm_provider = llm_provider  # callable returning the current LLMRouter
        self.session_factory = session_factory
        self.owner = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self._tasks: set[asyncio.Task] = set()

    # ---- bookkeeping ---------------------------------------------------------------------------

    @staticmethod
    def _event(db, run_id: str, event_type: str, node: str | None = None, data=None):
        db.add(AgentWorkflowEvents(run_id=run_id, event_type=event_type, node=node,
                                   data=redact(data) if data is not None else None, created_at=utcnow()))

    async def create_run(self, *, user_id: int, role: str, message: str, workflow_type: str = "chat",
                         conversation_id: str | None = None, file_ids: list[str] | None = None,
                         dispute_id: int | None = None, carry_over: dict | None = None,
                         correlation_id: str | None = None) -> str:
        run_id, now = str(uuid.uuid4()), utcnow()
        conversation_id = conversation_id or str(uuid.uuid4())
        correlation_id = correlation_id or uuid.uuid4().hex
        initial = {
            "workflow_id": run_id, "conversation_id": conversation_id, "correlation_id": correlation_id,
            "authenticated_user_id": user_id, "actor_role": role, "workflow_type": workflow_type,
            "messages": [{"role": "user", "content": message}], "file_ids": list(file_ids or []),
            "carry_over": carry_over or {}, "step_count": 0, "clarifications": 0, "status": RUNNING,
            **({"dispute": {"dispute_id": dispute_id}} if dispute_id else {}),
            **({"selected_listing_id": (carry_over or {}).get("selected_listing_id")}
               if (carry_over or {}).get("selected_listing_id") else {}),
        }
        async with self.session_factory() as db:
            db.add(AgentWorkflowRuns(
                id=run_id, conversation_id=conversation_id, user_id=user_id, actor_role=role,
                workflow_type=workflow_type, status=QUEUED, resume_payload={"input": initial}, attempts=0,
                correlation_id=correlation_id, created_at=now, updated_at=now,
            ))
            # No relationship() links the two models, so the unit of work doesn't order their
            # INSERTs; flush the run first or the event's foreign key can fail.
            await db.flush()
            self._event(db, run_id, "user_message", data={"content": message, "file_count": len(file_ids or [])})
            await db.commit()
        return run_id

    async def queue_resume(self, run_id: str, value: dict, expected: tuple[str, ...]) -> None:
        async with self.session_factory() as db:
            run = (await db.execute(select(AgentWorkflowRuns).where(AgentWorkflowRuns.id == run_id)
                                    .with_for_update())).scalar_one_or_none()
            if not run or run.status not in expected:
                raise RunNotResumable(f"run is {run.status if run else 'missing'}")
            run.status, run.resume_payload, run.pending = QUEUED, {"resume": value}, None
            run.waiting_on_type = run.waiting_on_id = run.waiting_marker = None
            run.next_attempt_at, run.updated_at = None, utcnow()
            self._event(db, run_id, "resume", data={"type": value.get("type") or value.get("event") or value.get("decision")})
            await db.commit()

    async def _claim(self, run_id: str) -> AgentWorkflowRuns | None:
        now = utcnow()
        async with self.session_factory() as db:
            result = await db.execute(
                update(AgentWorkflowRuns)
                .where(AgentWorkflowRuns.id == run_id, or_(
                    and_(AgentWorkflowRuns.status == QUEUED,
                         or_(AgentWorkflowRuns.next_attempt_at.is_(None), AgentWorkflowRuns.next_attempt_at <= now)),
                    and_(AgentWorkflowRuns.status == RUNNING, AgentWorkflowRuns.lease_until < now),
                ))
                .values(status=RUNNING, lease_owner=self.owner, lease_until=now + timedelta(seconds=settings().lease_s),
                        attempts=AgentWorkflowRuns.attempts + 1, updated_at=now)
                .returning(AgentWorkflowRuns)
            )
            run = result.scalar_one_or_none()
            await db.commit()
            return run

    async def _context(self, run: AgentWorkflowRuns) -> RunContext:
        async with self.session_factory() as db:
            user = await load_actor(db, run.user_id)
        return RunContext(run_id=run.id, user_id=user.id, role=user.role_name, correlation_id=run.correlation_id,
                          conversation_id=run.conversation_id, tools=self.tools, llm=self.llm_provider())

    # ---- driving ------------------------------------------------------------------------------

    async def drive(self, run_id: str) -> bool:
        """Run until the workflow pauses or ends. False if another worker holds the run."""
        run = await self._claim(run_id)
        if run is None:
            return False
        cfg = settings()
        payload = run.resume_payload or {}
        graph_input = payload["input"] if "input" in payload else Command(resume=payload["resume"]) \
            if "resume" in payload else None  # None: continue from the last checkpoint after a crash
        config = {"configurable": {"thread_id": run.id}, "recursion_limit": cfg.max_steps * 3}
        try:
            ctx = await self._context(run)
        except PolicyViolation as e:
            await self._finish(run.id, FAILED, error={"code": e.code, "message": e.message})
            return True
        async def stream():
            async for chunk in self.graph.astream(graph_input, config, context=ctx, durability="sync",
                                                  stream_mode="updates"):
                await self._trace(run.id, chunk)

        try:
            await asyncio.wait_for(stream(), timeout=cfg.inline_timeout_s)
            snapshot = await self.graph.aget_state(config)
        except StepLimitReached as e:
            await self._finish(run.id, FAILED, error={"code": "step_limit", "message": str(e)})
            return True
        except asyncio.TimeoutError:
            await self._retry_or_fail(run, {"code": "timeout", "message": "the run exceeded its time budget"})
            return True
        except Exception as e:  # unexpected: retry from the last checkpoint, then give up
            logger.exception(f"workflow {run.id} failed: {e}")
            await self._retry_or_fail(run, {"code": e.__class__.__name__, "message": str(e)[:300]})
            return True
        await self._settle(run, snapshot)
        return True

    async def _trace(self, run_id: str, chunk: dict):
        async with self.session_factory() as db:
            for node, update_ in chunk.items():
                if node == "__interrupt__":
                    self._event(db, run_id, "interrupt", data=[getattr(i, "value", None) for i in update_])
                    continue
                update_ = update_ or {}
                self._event(db, run_id, "node", node=node, data={
                    "next": update_.get("next"), "keys": sorted(update_.keys()),
                    "errors": update_.get("errors"), "security_flags": update_.get("security_flags"),
                })
            await db.commit()

    async def _settle(self, run: AgentWorkflowRuns, snapshot):
        state = snapshot.values or {}
        interrupts = list(snapshot.interrupts or ())
        now = utcnow()
        decided_early = None
        async with self.session_factory() as db:
            row = await db.get(AgentWorkflowRuns, run.id, with_for_update=True)
            row.lease_owner = row.lease_until = None
            row.resume_payload = None
            row.attempts = 0  # progress was made: max_attempts bounds consecutive failures, not pauses
            row.intent = state.get("intent") or row.intent
            row.current_node = (state.get("visited") or [None])[-1]
            row.updated_at = now
            if interrupts:
                value = dict(interrupts[0].value or {})
                kind = value.get("type")
                row.pending = value
                if kind == "approval":
                    row.status = ESCALATED if value.get("requested_for_role") else AWAITING_APPROVAL
                    approval = await db.get(AgentApprovalRequests, value.get("approval_id")) if value.get("approval_id") else None
                    if approval and approval.status != APPROVAL_PENDING:
                        decided_early = {"approval_id": approval.id, "decision": approval.status,
                                         "payload": approval.payload, "note": approval.decision_note}
                elif kind == "external":
                    row.status = WAITING_EXTERNAL
                    row.waiting_on_type, row.waiting_on_id = value.get("waiting_on"), value.get("negotiation_id")
                    row.waiting_marker = str(value.get("offer_id") or "")
                else:
                    row.status = AWAITING_INPUT
                self._event(db, run.id, "status", data={"status": row.status, "pending": value})
            else:
                response = state.get("response") or {}
                row.status, row.pending, row.completed_at = COMPLETED, None, now
                row.result = {"response": response, "carry_over": _carry_over(state)}
                self._event(db, run.id, "assistant_message", data={"content": response.get("message")})
                self._event(db, run.id, "status", data={"status": COMPLETED})
            await db.commit()
        if decided_early:  # the approver answered before the run reached its pause
            await self.queue_resume(run.id, decided_early, (AWAITING_APPROVAL, ESCALATED))
            self.schedule(run.id)

    async def _retry_payload(self, run_id: str, payload: dict | None) -> dict | None:
        """What the next attempt should feed the graph.

        - no checkpoint yet: the original input (the graph never started);
        - still paused at the interrupt the resume value was meant for: the same resume value;
        - otherwise None: continue from the last checkpoint (the input/resume was already consumed).
        """
        try:
            snapshot = await self.graph.aget_state({"configurable": {"thread_id": run_id}})
        except Exception:
            return payload
        if not snapshot or not snapshot.created_at:
            return payload
        if snapshot.interrupts and "resume" in (payload or {}):
            return payload
        return None

    async def _retry_or_fail(self, run: AgentWorkflowRuns, error: dict):
        cfg = settings()
        retry_payload = await self._retry_payload(run.id, run.resume_payload)
        async with self.session_factory() as db:
            row = await db.get(AgentWorkflowRuns, run.id, with_for_update=True)
            row.lease_owner = row.lease_until = None
            row.error = error
            row.updated_at = utcnow()
            if row.attempts >= cfg.max_attempts:
                row.status, row.completed_at = FAILED, utcnow()
            else:
                row.status = QUEUED
                row.resume_payload = retry_payload
                row.next_attempt_at = utcnow() + timedelta(seconds=min(300, 5 * 2 ** row.attempts))
            self._event(db, run.id, "error", data={**error, "attempts": row.attempts, "status": row.status})
            await db.commit()

    async def _finish(self, run_id: str, status: str, *, error: dict | None = None):
        async with self.session_factory() as db:
            row = await db.get(AgentWorkflowRuns, run_id, with_for_update=True)
            row.status, row.error, row.completed_at = status, error, utcnow()
            row.lease_owner = row.lease_until = None
            row.updated_at = utcnow()
            self._event(db, run_id, "status", data={"status": status, "error": error})
            await db.commit()

    # ---- background --------------------------------------------------------------------------------

    def schedule(self, run_id: str):
        task = asyncio.get_running_loop().create_task(self._safe_drive(run_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _safe_drive(self, run_id: str):
        try:
            await self.drive(run_id)
        except Exception as e:
            logger.exception(f"background drive of {run_id} failed: {e}")

    async def process_queue(self, limit: int | None = None) -> int:
        now = utcnow()
        async with self.session_factory() as db:
            ids = (await db.execute(
                select(AgentWorkflowRuns.id).where(or_(
                    and_(AgentWorkflowRuns.status == QUEUED,
                         or_(AgentWorkflowRuns.next_attempt_at.is_(None), AgentWorkflowRuns.next_attempt_at <= now)),
                    and_(AgentWorkflowRuns.status == RUNNING, AgentWorkflowRuns.lease_until < now),
                )).order_by(AgentWorkflowRuns.updated_at).limit(limit or settings().worker_batch)
            )).scalars().all()
        driven = 0
        for run_id in ids:
            driven += 1 if await self.drive(run_id) else 0
        return driven

    async def wake_external(self, run_id: str | None = None) -> int:
        """Re-queue runs waiting on a negotiation that has moved on since the wait began."""
        async with self.session_factory() as db:
            stmt = (
                select(AgentWorkflowRuns.id, Negotiations.status, Negotiations.current_offer_id, Offers.status)
                .join(Negotiations, Negotiations.id == AgentWorkflowRuns.waiting_on_id)
                .outerjoin(Offers, Offers.id == Negotiations.current_offer_id)
                .where(AgentWorkflowRuns.status == WAITING_EXTERNAL, AgentWorkflowRuns.waiting_on_type == "negotiation",
                       or_(Negotiations.status != "OPEN", Offers.status != "PENDING",
                           text("CAST(negotiations.current_offer_id AS TEXT) IS DISTINCT FROM agent_workflow_runs.waiting_marker")))
                .limit(50)
            )
            if run_id:
                stmt = stmt.where(AgentWorkflowRuns.id == run_id)
            rows = (await db.execute(stmt)).all()
        woken = 0
        for rid, neg_status, offer_id, offer_status in rows:
            try:
                await self.queue_resume(rid, {"event": "negotiation_update", "negotiation_status": neg_status,
                                              "current_offer_id": offer_id, "offer_status": offer_status},
                                        (WAITING_EXTERNAL,))
                woken += 1
                if settings().inline_execution:
                    self.schedule(rid)
            except RunNotResumable:
                continue
        return woken

    async def expire_approvals(self) -> int:
        now = utcnow()
        async with self.session_factory() as db:
            rows = (await db.execute(select(AgentApprovalRequests).where(
                AgentApprovalRequests.status == APPROVAL_PENDING, AgentApprovalRequests.expires_at < now,
            ).with_for_update(skip_locked=True).limit(100))).scalars().all()
            for row in rows:
                row.status, row.decided_at = APPROVAL_EXPIRED, now
            await db.commit()
        for row in rows:
            try:
                await self.queue_resume(row.run_id, {"approval_id": row.id, "decision": APPROVAL_EXPIRED},
                                        (AWAITING_APPROVAL, ESCALATED))
            except RunNotResumable:
                continue
        return len(rows)

    async def cancel(self, run_id: str, user_id: int | None, *, is_admin: bool = False) -> None:
        async with self.session_factory() as db:
            row = await db.get(AgentWorkflowRuns, run_id, with_for_update=True)
            if not row or (not is_admin and row.user_id != user_id):
                raise RunNotResumable("run not found")
            if row.status in TERMINAL_STATES or row.status == RUNNING:
                raise RunNotResumable(f"run is {row.status}")
            row.status, row.completed_at, row.updated_at = CANCELLED, utcnow(), utcnow()
            row.pending = row.resume_payload = None
            await db.execute(update(AgentApprovalRequests).where(
                AgentApprovalRequests.run_id == run_id, AgentApprovalRequests.status == APPROVAL_PENDING,
            ).values(status=APPROVAL_SUPERSEDED, decided_at=utcnow()))
            self._event(db, run_id, "status", data={"status": CANCELLED})
            await db.commit()

    async def retry_failed(self, run_id: str) -> None:
        async with self.session_factory() as db:
            current = await db.get(AgentWorkflowRuns, run_id)
            payload = await self._retry_payload(run_id, current.resume_payload) if current else None
        async with self.session_factory() as db:
            row = await db.get(AgentWorkflowRuns, run_id, with_for_update=True)
            if not row or row.status != FAILED:
                raise RunNotResumable("only failed runs can be retried")
            row.resume_payload = payload
            row.status, row.attempts, row.next_attempt_at, row.error = QUEUED, 0, None, None
            row.completed_at, row.updated_at = None, utcnow()
            self._event(db, run_id, "status", data={"status": QUEUED, "retried": True})
            await db.commit()

    async def aclose(self):
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)


__all__ = ["WorkflowRunner", "RunNotResumable", "PAUSED_STATES"]
