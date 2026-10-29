"""
request_human_approval: freeze a validated action for a human to approve.

The payload is validated with the target tool's own schema before it is stored, and hashed; the
executor later refuses to run that tool with anything else. Creation is idempotent per
(run, step_key), because LangGraph re-runs a node from the top when it resumes.
"""
from datetime import timedelta
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.config import settings
from src.agents.context import RunContext
from src.agents.tools.base import REGISTRY, canonical, payload_hash, tool, validate_args
from src.data_models.agents_model import AgentApprovalRequests, APPROVAL_PENDING
from src.data_models.roles_model import Roles
from src.data_models.users_model import Users
from src.services.notifications_service import notify_user
from src.core.clock import utcnow


class ApprovalInput(BaseModel):
    action: str = Field(..., max_length=40)
    step_key: str = Field(..., min_length=1, max_length=80)
    payload: dict
    summary: str = Field(..., min_length=3, max_length=500)
    editable_fields: list[str] = Field(default_factory=list, max_length=10)
    context: dict = Field(default_factory=dict)
    requested_for_role: Literal["admin"] | None = None


def approval_view(row: AgentApprovalRequests) -> dict:
    return {
        "approval_id": row.id, "run_id": row.run_id, "action": row.action, "status": row.status,
        "summary": row.summary, "payload": row.payload, "editable_fields": row.editable_fields or [],
        "context": row.context or {}, "requested_for": row.requested_for,
        "requested_for_role": row.requested_for_role, "expires_at": row.expires_at, "created_at": row.created_at,
        "decided_at": row.decided_at, "reviewed_by": row.reviewed_by, "decision_note": row.decision_note,
    }


@tool("request_human_approval", ApprovalInput, "Ask the user (or an admin) to approve a consequential action.")
async def request_human_approval(db: AsyncSession, actor: Users, args: ApprovalInput, ctx: RunContext) -> dict:
    if not ctx.run_id:
        raise HTTPException(status_code=409, detail="Approvals belong to a workflow run.")
    spec = REGISTRY.get(args.action)
    if spec is None or not spec.policy.requires_approval:
        raise HTTPException(status_code=422, detail=f"'{args.action}' is not an approval-gated action.")
    if args.requested_for_role is None and actor.role_name not in spec.policy.roles:
        raise HTTPException(status_code=403, detail=f"A {actor.role_name} can't perform '{args.action}'.")
    payload = canonical(validate_args(args.action, args.payload))
    unknown = set(args.editable_fields) - set(payload)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Not fields of {args.action}: {', '.join(sorted(unknown))}")

    existing = (await db.execute(select(AgentApprovalRequests).where(
        AgentApprovalRequests.run_id == ctx.run_id, AgentApprovalRequests.step_key == args.step_key,
    ))).scalar_one_or_none()
    if existing:
        return {**approval_view(existing), "created": False}

    now = utcnow()
    row = AgentApprovalRequests(
        run_id=ctx.run_id, step_key=args.step_key, action=args.action,
        requested_for=None if args.requested_for_role else actor.id, requested_for_role=args.requested_for_role,
        summary=args.summary, payload=payload, payload_hash=payload_hash(payload),
        editable_fields=args.editable_fields, context=canonical(args.context), status=APPROVAL_PENDING,
        expires_at=now + timedelta(hours=settings().approval_ttl_hours), created_at=now,
    )
    db.add(row)
    await db.flush()
    recipients = [actor.id] if not args.requested_for_role else (await db.execute(
        select(Users.id).join(Roles, Users.role_id == Roles.id)
        .where(func.lower(Roles.name) == args.requested_for_role, Users.deleted_at.is_(None))
    )).scalars().all()
    for user_id in recipients:
        await notify_user(db, user_id, "agent_approval_needed", {"summary": args.summary[:200]},
                          ref_type="agent_approval", ref_id=row.id, dedupe_key=f"agent_approval:{row.id}:{user_id}")
    return {**approval_view(row), "created": True}
