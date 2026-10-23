"""Admin oversight (read-only) and admin-initiated notifications."""
import hashlib
from datetime import timedelta

from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.context import RunContext
from src.agents.tools.base import tool
from src.data_models.agents_model import (
    AgentApprovalRequests, AgentModelCalls, AgentToolCalls, AgentWorkflowRuns, APPROVAL_PENDING, ESCALATED, FAILED,
    TOOL_DENIED,
)
from src.data_models.disputes_model import Disputes, ACTIVE_DISPUTE_STATES
from src.data_models.farmer_inventory_model import FarmerInventory
from src.data_models.platform_model import Reports
from src.data_models.users_model import Users
from src.services.admin_service import AdminService
from src.services.notifications_service import notify_user
from src.core.clock import utcnow


class OverviewInput(BaseModel):
    days: int = Field(7, ge=1, le=90)


@tool("admin_overview", OverviewInput,
      "Flagged listings, suspicious activity, disputes, failed or escalated workflows and model usage.")
async def admin_overview(db: AsyncSession, actor: Users, args: OverviewInput, ctx: RunContext) -> dict:
    since = utcnow() - timedelta(days=args.days)
    flagged = (await db.execute(
        select(Reports.target_id, func.count(Reports.id), func.max(Reports.created_at))
        .where(Reports.target_type == "listing", Reports.status == "open").group_by(Reports.target_id)
        .order_by(func.count(Reports.id).desc()).limit(20)
    )).all()
    listing_status = dict((await db.execute(select(FarmerInventory.id, FarmerInventory.status).where(
        FarmerInventory.id.in_([f[0] for f in flagged] or [0])))).all())
    disputes = (await db.execute(select(Disputes.id, Disputes.order_id, Disputes.reason, Disputes.escalated,
                                        Disputes.created_at).where(Disputes.status.in_(ACTIVE_DISPUTE_STATES))
                                 .order_by(Disputes.escalated.desc(), Disputes.created_at).limit(20))).all()
    runs = (await db.execute(select(AgentWorkflowRuns.id, AgentWorkflowRuns.status, AgentWorkflowRuns.workflow_type,
                                    AgentWorkflowRuns.intent, AgentWorkflowRuns.error, AgentWorkflowRuns.updated_at)
                             .where(AgentWorkflowRuns.status.in_((FAILED, ESCALATED)),
                                    AgentWorkflowRuns.updated_at >= since)
                             .order_by(AgentWorkflowRuns.updated_at.desc()).limit(20))).all()
    pending_admin = (await db.execute(select(func.count(AgentApprovalRequests.id)).where(
        AgentApprovalRequests.requested_for_role == "admin", AgentApprovalRequests.status == APPROVAL_PENDING))).scalar()
    usage = (await db.execute(
        select(AgentModelCalls.model_id, AgentModelCalls.task, func.count(AgentModelCalls.id),
               func.sum(case((AgentModelCalls.status != "ok", 1), else_=0)), func.avg(AgentModelCalls.latency_ms),
               func.sum(AgentModelCalls.input_tokens), func.sum(AgentModelCalls.output_tokens),
               func.sum(AgentModelCalls.cost_usd))
        .where(AgentModelCalls.created_at >= since)
        .group_by(AgentModelCalls.model_id, AgentModelCalls.task)
    )).all()
    denials = (await db.execute(select(AgentToolCalls.tool, func.count(AgentToolCalls.id)).where(
        AgentToolCalls.status == TOOL_DENIED, AgentToolCalls.created_at >= since).group_by(AgentToolCalls.tool))).all()
    return {
        "period_days": args.days,
        "flagged_listings": [{"listing_id": lid, "open_reports": n, "last_report_at": last,
                              "listing_status": listing_status.get(lid)} for lid, n, last in flagged],
        "suspicious_activity": await AdminService().monitoring(db, args.days),
        "open_disputes": [{"dispute_id": d, "order_id": o, "reason": r, "escalated": e, "opened_at": c}
                          for d, o, r, e, c in disputes],
        "workflow_issues": [{"run_id": rid, "status": st, "workflow_type": wt, "intent": it,
                             "error": (err or {}).get("code") if isinstance(err, dict) else None, "updated_at": up}
                            for rid, st, wt, it, err, up in runs],
        "pending_admin_approvals": pending_admin,
        "model_usage": [{"model_id": m, "task": t, "calls": n, "errors": int(e or 0),
                         "avg_latency_ms": round(float(lat or 0)), "input_tokens": int(i or 0),
                         "output_tokens": int(o or 0), "cost_usd": float(cost) if cost is not None else None}
                        for m, t, n, e, lat, i, o, cost in usage],
        "denied_tool_calls": {tool_name: n for tool_name, n in denials},
    }


class NotifyInput(BaseModel):
    user_id: int = Field(..., gt=0)
    summary: str = Field(..., min_length=3, max_length=300)


@tool("send_notification", NotifyInput, "Send an in-app notification to a user (admin only).")
async def send_notification(db: AsyncSession, actor: Users, args: NotifyInput, ctx: RunContext) -> dict:
    digest = hashlib.sha1(args.summary.encode("utf-8")).hexdigest()[:12]
    created = await notify_user(db, args.user_id, "agent_update", {"summary": args.summary},
                                ref_type="agent_run", dedupe_key=f"agent_notify:{ctx.run_id}:{args.user_id}:{digest}")
    await db.commit()
    return {"notified": bool(created), "user_id": args.user_id}
