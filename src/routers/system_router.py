import os
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.observability import metrics
from src.core.scheduler import run_jobs
from src.data_models.users_model import Users
from src.db_connections.database import get_db_async
from src.security_utils.role_guard import require_roles, ADMIN

router = APIRouter(tags=["System"])


class RunJobsSchema(BaseModel):
    jobs: Optional[list[str]] = None


@router.get("/health")
async def liveness():
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(db: AsyncSession = Depends(get_db_async)):
    checks = {}
    try:
        await db.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {e.__class__.__name__}"
    if os.getenv("OTP_STORE", "mongo").lower() == "mongo":
        try:
            from src.db_connections.mongo_conn import get_mongo_client

            await get_mongo_client().admin.command("ping")
            checks["mongodb"] = "ok"
        except Exception as e:
            checks["mongodb"] = f"error: {e.__class__.__name__}"
    healthy = all(v == "ok" for v in checks.values())
    if not healthy:
        raise HTTPException(status_code=503, detail={"status": "degraded", "checks": checks})
    return {"status": "ok", "checks": checks, "components": await _agent_components(db)}


async def _agent_components(db: AsyncSession) -> dict:
    """Optional components: reported for operators, never failing readiness (the marketplace works without them)."""
    from src.agents.runtime import runtime

    components = {"agents": "ok" if runtime.ready else f"unavailable: {runtime.error or 'not started'}"}
    try:
        extensions = set((await db.execute(text(
            "SELECT extname FROM pg_extension WHERE extname IN ('postgis', 'vector')"))).scalars().all())
        components["postgis"] = "ok" if "postgis" in extensions else "missing"
        components["pgvector"] = "ok" if "vector" in extensions else "missing"
    except Exception as e:
        components["extensions"] = f"error: {e.__class__.__name__}"
    if runtime.ready:
        from src.agents.llm import get_router

        router = get_router()
        components["llm_models_available"] = len(router.registry.available())
        components["llm_circuits_open"] = sum(1 for s in router.circuit.snapshot().values() if s["open"])
    return components


@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics(x_metrics_token: Optional[str] = Header(None)):
    """Prometheus text format. Requires the X-Metrics-Token header to match METRICS_TOKEN."""
    expected = os.getenv("METRICS_TOKEN")
    if not expected or x_metrics_token != expected:
        raise HTTPException(status_code=404, detail="Not found")
    return metrics.prometheus()


@router.get("/api/admin/metrics")
async def admin_metrics(user: Users = Depends(require_roles(ADMIN))):
    return metrics.snapshot()


@router.post("/api/admin/jobs/run")
async def run_background_jobs(payload: RunJobsSchema, user: Users = Depends(require_roles(ADMIN))):
    """Run background jobs now (expiry, timeouts, notifications, recurring orders, ...)."""
    return await run_jobs(set(payload.jobs) if payload.jobs else None, force=True)
