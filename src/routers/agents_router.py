from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.tools.discovery import SearchListingsInput, VendorDemandInput
from src.core.idempotency import run_idempotent
from src.core.rate_limit import client_ip
from src.data_models.users_model import Users
from src.db_connections.database import get_db_async
from src.schemas.agents_schema import (
    ApprovalDecision, ChatRequest, ImageAnalysisRequest, InvestigateRequest, ListingFromImages, WorkflowInput,
)
from src.security_utils.role_guard import ADMIN, FARMER, VENDOR, require_roles
from src.services.agents_service import AgentsService

router = APIRouter(prefix="/api/agents", tags=["Agents"])
ANY_ROLE = require_roles(FARMER, VENDOR, ADMIN)


def agents_service() -> AgentsService:
    return AgentsService()


def _respond(result: tuple[dict, int] | dict):
    body, code = result if isinstance(result, tuple) else (result, 200)
    return JSONResponse(status_code=code, content=jsonable_encoder(body))


# ---- workflows -----------------------------------------------------------------------------------

@router.post("/chat")
async def chat(payload: ChatRequest, db: AsyncSession = Depends(get_db_async),
               service: AgentsService = Depends(agents_service), user: Users = Depends(ANY_ROLE),
               idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """
    Talk to the assistant. Starts a workflow (or answers one that asked a question, with
    `workflow_id`). The response is the workflow: `status` is completed, awaiting_input
    (see `pending.question`), awaiting_approval (approve via /approvals/{id}/decision),
    waiting_external (waiting for the other party), escalated (waiting for an admin) or failed.
    """
    async def action():
        body, code = await service.chat(user, payload, db)
        return {"body": body, "code": code}

    result = await run_idempotent(db, idempotency_key, user.id, "agents.chat", payload.model_dump(), action)
    return _respond((result["body"], result["code"]))


@router.get("/workflows")
async def list_workflows(status: Optional[str] = None, page: int = Query(1, ge=1),
                         page_size: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_db_async),
                         service: AgentsService = Depends(agents_service), user: Users = Depends(ANY_ROLE)):
    return await service.list_runs(user, db, status, page, page_size)


@router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str, db: AsyncSession = Depends(get_db_async),
                       service: AgentsService = Depends(agents_service), user: Users = Depends(ANY_ROLE)):
    return _respond(await service.get_run(user, workflow_id, db))


@router.get("/workflows/{workflow_id}/events")
async def workflow_events(workflow_id: str, after_id: Optional[int] = None, db: AsyncSession = Depends(get_db_async),
                          service: AgentsService = Depends(agents_service), user: Users = Depends(ANY_ROLE)):
    """Redacted trace: messages, node transitions, interrupts, tool calls, errors."""
    return await service.events(user, workflow_id, after_id, db)


@router.post("/workflows/{workflow_id}/input")
async def workflow_input(workflow_id: str, payload: WorkflowInput, db: AsyncSession = Depends(get_db_async),
                         service: AgentsService = Depends(agents_service), user: Users = Depends(ANY_ROLE)):
    """Answer the question a workflow asked (status awaiting_input)."""
    return _respond(await service.provide_input(user, workflow_id, payload.text, db))


@router.post("/workflows/{workflow_id}/cancel")
async def cancel_workflow(workflow_id: str, service: AgentsService = Depends(agents_service),
                          user: Users = Depends(ANY_ROLE)):
    return _respond(await service.cancel(user, workflow_id))


# ---- approvals -------------------------------------------------------------------------------------

@router.get("/approvals")
async def list_approvals(status: Optional[str] = None, db: AsyncSession = Depends(get_db_async),
                         service: AgentsService = Depends(agents_service), user: Users = Depends(ANY_ROLE)):
    """Actions waiting for your decision (admins also see the admin review queue)."""
    return _respond(await service.list_approvals(user, db, status))


@router.get("/approvals/{approval_id}")
async def get_approval(approval_id: int, db: AsyncSession = Depends(get_db_async),
                       service: AgentsService = Depends(agents_service), user: Users = Depends(ANY_ROLE)):
    return _respond(await service.get_approval(user, approval_id, db))


@router.post("/approvals/{approval_id}/decision")
async def decide_approval(approval_id: int, payload: ApprovalDecision, request: Request,
                          db: AsyncSession = Depends(get_db_async), service: AgentsService = Depends(agents_service),
                          user: Users = Depends(ANY_ROLE)):
    """
    Approve (optionally editing the editable fields) or reject a proposed action. Only an approved,
    unchanged-since-approval action runs, with your authority, exactly once.
    """
    return _respond(await service.decide(user, approval_id, payload, db, client_ip(request)))


# ---- specialist entry points -------------------------------------------------------------------------

@router.post("/discovery/search")
async def discovery_search(payload: SearchListingsInput, service: AgentsService = Depends(agents_service),
                           user: Users = Depends(require_roles(VENDOR, FARMER, ADMIN))):
    """Structured hybrid supplier search (hard filters, PostGIS radius, lexical + semantic ranking)."""
    return _respond(await service.direct_tool(user, "search_listings", payload.model_dump(mode="json")))


@router.post("/discovery/vendor-demand")
async def discovery_vendor_demand(payload: VendorDemandInput, service: AgentsService = Depends(agents_service),
                                  user: Users = Depends(require_roles(FARMER))):
    """Vendors with open buy requests or alerts that match your produce."""
    return _respond(await service.direct_tool(user, "search_vendor_demand", payload.model_dump(mode="json")))


@router.post("/images/analyze")
async def analyze_image(payload: ImageAnalysisRequest, service: AgentsService = Depends(agents_service),
                        user: Users = Depends(ANY_ROLE)):
    """Visual produce assessment of an uploaded photo (a visual estimate, never a certified grade)."""
    return _respond(await service.direct_tool(user, "analyze_produce_image", payload.model_dump()))


@router.post("/listings/from-images")
async def listing_from_images(payload: ListingFromImages, db: AsyncSession = Depends(get_db_async),
                              service: AgentsService = Depends(agents_service), user: Users = Depends(require_roles(FARMER)),
                              idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """Image-assisted listing: photos -> analysis -> draft for your review -> created only after you approve."""
    async def action():
        body, code = await service.listing_from_images(user, payload, db)
        return {"body": body, "code": code}

    result = await run_idempotent(db, idempotency_key, user.id, "agents.listing_from_images", payload.model_dump(), action)
    return _respond((result["body"], result["code"]))


@router.post("/disputes/{dispute_id}/investigate")
async def investigate_dispute(dispute_id: int, payload: InvestigateRequest = InvestigateRequest(),
                              db: AsyncSession = Depends(get_db_async), service: AgentsService = Depends(agents_service),
                              user: Users = Depends(ANY_ROLE)):
    """Evidence-linked investigation report for an admin; an admin decides the outcome."""
    return _respond(await service.investigate_dispute(user, dispute_id, payload, db))


@router.get("/disputes/{dispute_id}/reports")
async def dispute_reports(dispute_id: int, db: AsyncSession = Depends(get_db_async),
                          service: AgentsService = Depends(agents_service), user: Users = Depends(ANY_ROLE)):
    return _respond(await service.dispute_reports(user, dispute_id, db))


# ---- admin -------------------------------------------------------------------------------------------

@router.get("/admin/overview")
async def admin_overview(days: int = Query(7, ge=1, le=90), service: AgentsService = Depends(agents_service),
                         user: Users = Depends(require_roles(ADMIN))):
    """Flagged listings, suspicious activity, disputes, failed/escalated workflows, model usage."""
    return _respond(await service.direct_tool(user, "admin_overview", {"days": days}))


@router.get("/admin/models")
async def admin_models(days: int = Query(7, ge=1, le=90), db: AsyncSession = Depends(get_db_async),
                       service: AgentsService = Depends(agents_service), user: Users = Depends(require_roles(ADMIN))):
    """Model registry, capabilities, availability, circuit breakers, usage, latency and cost."""
    return _respond(await service.models_status(db, days))


@router.get("/admin/workflows")
async def admin_workflows(status: Optional[str] = None, page: int = Query(1, ge=1),
                          page_size: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_db_async),
                          service: AgentsService = Depends(agents_service), user: Users = Depends(require_roles(ADMIN))):
    return await service.list_runs(user, db, status, page, page_size, all_users=True)


@router.post("/admin/workflows/{workflow_id}/retry")
async def admin_retry(workflow_id: str, service: AgentsService = Depends(agents_service),
                      user: Users = Depends(require_roles(ADMIN))):
    return _respond(await service.admin_retry(workflow_id))
