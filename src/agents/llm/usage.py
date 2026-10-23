"""Persists one row per model call (metadata only: no prompts, no outputs, no keys)."""

from src.db_connections.database import AsyncSessionLocal
from src.core.clock import utcnow


async def record_model_call(**fields):
    from src.data_models.agents_model import AgentModelCalls

    # Own short session: the caller may be mid-transaction, and a failed workflow must still be observable.
    async with AsyncSessionLocal() as db:
        db.add(AgentModelCalls(**fields, created_at=utcnow()))
        await db.commit()
