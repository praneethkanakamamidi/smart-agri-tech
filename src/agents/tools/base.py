"""
Tool registry and executor: the only way an agent touches business data.

For every call the executor
  1. resolves the tool and its policy (src/agents/policy.py);
  2. for approval-gated tools, loads the approval request, requires it to be approved, for this
     run and this tool, with a payload hash equal to the hash of the arguments - so a model can't
     execute anything other than what the human approved - and acts with the *approver's*
     identity;
  3. reloads the acting user from the database (must exist, be active, and have a role the
     policy allows) - identity never comes from model output or graph state;
  4. validates the arguments with the tool's pydantic schema;
  5. for mutations, enforces exactly-once: an AgentToolCalls row with the idempotency key is
     added to the same session *before* the domain service runs, so it commits atomically with
     the side effect; a retry with the same key replays the stored result, and a concurrent
     duplicate fails on the partial unique index and is rolled back;
  6. maps domain errors (HTTPException from the services) to typed ToolErrors and records every
     outcome - succeeded, failed, denied, replayed - with redacted arguments.
"""
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.context import RunContext
from src.agents.policy import PolicyViolation, ToolPolicy, authorize_tool, tool_policy
from src.agents.redaction import redact
from src.core.audit import audit
from src.core.lookups import misc_value
from src.core.observability import CODES
from src.data_models.agents_model import (
    AgentApprovalRequests, AgentToolCalls, APPROVAL_APPROVED, TOOL_DENIED, TOOL_FAILED, TOOL_REPLAYED, TOOL_SUCCEEDED,
)
from src.data_models.users_model import Users
from src.db_connections.database import AsyncSessionLocal
from src.helpers.logging_config import get_logger
from src.security_utils.role_guard import get_role_name

logger = get_logger("agents.tools")

Handler = Callable[[AsyncSession, Users, BaseModel, RunContext], Awaitable[dict]]


class ToolError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, retriable: bool = False):
        super().__init__(message)
        self.code, self.message, self.status, self.retriable = code, message, status, retriable

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "status": self.status}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Handler
    policy: ToolPolicy


REGISTRY: dict[str, ToolSpec] = {}


def tool(name: str, input_model: type[BaseModel], description: str):
    """Register a tool. Its policy must already be declared in TOOL_POLICIES (single source of truth)."""
    policy = tool_policy(name)

    def decorator(fn: Handler) -> Handler:
        REGISTRY[name] = ToolSpec(name, description, input_model, fn, policy)
        return fn

    return decorator


def canonical(payload: BaseModel | dict) -> dict:
    data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    return json.loads(json.dumps(jsonable_encoder(data), sort_keys=True, default=str))


def payload_hash(payload: BaseModel | dict) -> str:
    return hashlib.sha256(json.dumps(canonical(payload), sort_keys=True).encode()).hexdigest()


def validate_args(name: str, args: BaseModel | dict) -> BaseModel:
    spec = REGISTRY.get(name)
    if spec is None:
        raise ToolError("unknown_tool", f"Tool '{name}' is not available.", 404)
    try:
        data = args.model_dump(mode="json") if isinstance(args, BaseModel) else args
        return spec.input_model.model_validate(data)
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()[:6])
        raise ToolError("invalid_arguments", f"Invalid arguments for {name}: {problems}", 422) from e


async def load_actor(db: AsyncSession, user_id: int | None) -> Users:
    user = await db.get(Users, user_id) if user_id else None
    if not user or user.deleted_at:
        raise PolicyViolation("account_unavailable", "The acting account no longer exists.")
    if await misc_value(db, user.status) != "active":
        raise PolicyViolation("account_inactive", "The acting account is not active.")
    user.role_name = await get_role_name(user, db)
    return user


def _summary(result: Any) -> Any:
    return redact(jsonable_encoder(result))


def _http_code(status: int) -> str:
    return CODES.get(status, "error")


class ToolExecutor:
    def __init__(self, session_factory=AsyncSessionLocal):
        self.session_factory = session_factory

    async def _record(self, ctx: RunContext, name: str, kind: str, status: str, *, args, user_id=None,
                      approval_id=None, key=None, result=None, error: ToolError | None = None, started: float):
        try:
            async with self.session_factory() as db:
                db.add(AgentToolCalls(
                    run_id=ctx.run_id, user_id=user_id, approval_id=approval_id, node=ctx.node, tool=name, kind=kind,
                    status=status, idempotency_key=key if status != TOOL_SUCCEEDED else None, args=redact(args),
                    result=_summary(result) if result is not None else None,
                    error_code=error.code if error else None, error_message=error.message[:255] if error else None,
                    latency_ms=int((time.perf_counter() - started) * 1000), created_at=datetime.utcnow(),
                ))
                await db.commit()
        except Exception as e:  # recording must never mask the original outcome
            logger.warning(f"could not record tool call {name}: {e.__class__.__name__}")

    async def _approval(self, db: AsyncSession, ctx: RunContext, name: str, approval_id: int | None,
                        parsed: BaseModel) -> AgentApprovalRequests:
        if approval_id is None:
            raise PolicyViolation("approval_required", f"'{name}' needs an approved request before it can run.")
        approval = await db.get(AgentApprovalRequests, approval_id)
        if not approval or approval.run_id != ctx.run_id or approval.action != name:
            raise PolicyViolation("approval_mismatch", "The approval doesn't belong to this action.")
        if approval.status != APPROVAL_APPROVED or not approval.reviewed_by:
            raise PolicyViolation("approval_not_granted", f"The approval is {approval.status}.")
        if approval.payload_hash != payload_hash(parsed):
            raise PolicyViolation("approval_payload_changed", "The action differs from what was approved.")
        return approval

    async def _authorised_approver(self, db: AsyncSession, approval: AgentApprovalRequests) -> Users:
        approver = await load_actor(db, approval.reviewed_by)
        if approval.requested_for is not None and approval.requested_for != approver.id:
            raise PolicyViolation("approver_mismatch", "This approval was decided by the wrong account.")
        if approval.requested_for is None and approval.requested_for_role != approver.role_name:
            raise PolicyViolation("approver_mismatch", "This approval needs a different role.")
        return approver

    async def _replay(self, db: AsyncSession, key: str) -> dict | None:
        prior = (await db.execute(select(AgentToolCalls).where(
            AgentToolCalls.idempotency_key == key, AgentToolCalls.status == TOOL_SUCCEEDED,
        ))).scalar_one_or_none()
        if prior is None:
            return None
        return {**(prior.result or {}), "replayed": True, "original_tool_call_id": prior.id}

    async def call(self, ctx: RunContext, name: str, args: BaseModel | dict, *, approval_id: int | None = None,
                   idempotency_key: str | None = None) -> dict:
        started = time.perf_counter()
        raw_args = args.model_dump(mode="json") if isinstance(args, BaseModel) else dict(args or {})
        spec = REGISTRY.get(name)
        if spec is None:
            error = ToolError("unknown_tool", f"Tool '{name}' is not available.", 404)
            await self._record(ctx, name, "read", TOOL_DENIED, args=raw_args, user_id=ctx.user_id, error=error,
                               started=started)
            raise error
        kind = spec.policy.kind
        acting_user_id, approval_ref = ctx.user_id, approval_id
        key = idempotency_key
        try:
            parsed = validate_args(name, raw_args)
        except ToolError as error:
            await self._record(ctx, name, kind, TOOL_DENIED, args=raw_args, user_id=acting_user_id,
                               approval_id=approval_ref, error=error, started=started)
            raise

        async with self.session_factory() as db:
            record = None
            try:
                if spec.policy.requires_approval:
                    approval = await self._approval(db, ctx, name, approval_id, parsed)
                    actor = await self._authorised_approver(db, approval)
                    key = key or f"approval:{approval.id}:{name}"
                else:
                    actor = await load_actor(db, ctx.user_id)
                acting_user_id = actor.id
                authorize_tool(actor.role_name, name)

                if kind == "mutate":
                    if not key:
                        raise PolicyViolation("idempotency_key_required", f"'{name}' needs an idempotency key.")
                    replay = await self._replay(db, key)
                    if replay is not None:
                        await self._record(ctx, name, kind, TOOL_REPLAYED, args=raw_args, user_id=actor.id,
                                           approval_id=approval_ref, key=key, result=replay, started=started)
                        return replay
                    # Same transaction as the side effect: commits with it or not at all.
                    record = AgentToolCalls(
                        run_id=ctx.run_id, user_id=actor.id, approval_id=approval_ref, node=ctx.node, tool=name,
                        kind=kind, status=TOOL_SUCCEEDED, idempotency_key=key, args=redact(raw_args),
                        created_at=datetime.utcnow(),
                    )
                    db.add(record)
                    audit(db, f"agent.{name}", "agent_run", ctx.run_id, actor_id=actor.id, actor_role=actor.role_name,
                          after={"approval_id": approval_ref, "node": ctx.node, "correlation_id": ctx.correlation_id})

                result = await spec.handler(db, actor, parsed, ctx.at(ctx.node or name))

                if record is None:
                    record = AgentToolCalls(
                        run_id=ctx.run_id, user_id=actor.id, approval_id=approval_ref, node=ctx.node, tool=name,
                        kind=kind, status=TOOL_SUCCEEDED, args=redact(raw_args), created_at=datetime.utcnow(),
                    )
                    db.add(record)
                record.result = _summary(result)
                record.latency_ms = int((time.perf_counter() - started) * 1000)
                await db.commit()
                return result
            except PolicyViolation as e:
                await db.rollback()
                error = ToolError(e.code, e.message, 403)
                await self._record(ctx, name, kind, TOOL_DENIED, args=raw_args, user_id=acting_user_id,
                                   approval_id=approval_ref, key=key, error=error, started=started)
                raise error from e
            except HTTPException as e:
                await db.rollback()
                detail = e.detail if isinstance(e.detail, str) else json.dumps(jsonable_encoder(e.detail))[:250]
                error = ToolError(_http_code(e.status_code), detail, e.status_code)
                await self._record(ctx, name, kind, TOOL_FAILED, args=raw_args, user_id=acting_user_id,
                                   approval_id=approval_ref, key=key, error=error, started=started)
                raise error from e
            except IntegrityError as e:
                await db.rollback()
                if kind == "mutate" and key:
                    replay = await self._replay(db, key)
                    if replay is not None:  # a concurrent duplicate won the race; its effect is the one that counts
                        await self._record(ctx, name, kind, TOOL_REPLAYED, args=raw_args, user_id=acting_user_id,
                                           approval_id=approval_ref, key=key, result=replay, started=started)
                        return replay
                error = ToolError("conflict", "The change conflicted with another update. Please retry.", 409, True)
                await self._record(ctx, name, kind, TOOL_FAILED, args=raw_args, user_id=acting_user_id,
                                   approval_id=approval_ref, key=key, error=error, started=started)
                raise error from e
            except ToolError as error:
                await db.rollback()
                await self._record(ctx, name, kind, TOOL_FAILED, args=raw_args, user_id=acting_user_id,
                                   approval_id=approval_ref, key=key, error=error, started=started)
                raise


def tool_catalogue(role: str | None = None) -> list[dict]:
    """Tools (optionally only those a role may use) as model-facing function specs."""
    from src.agents.llm.structured import json_schema

    return [
        {"name": s.name, "description": s.description, "kind": s.policy.kind,
         "requires_approval": s.policy.requires_approval, "parameters": json_schema(s.input_model)}
        for s in REGISTRY.values() if role is None or role in s.policy.roles
    ]
