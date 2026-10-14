"""Persists one row per model call (metadata only: no prompts, no outputs, no keys)."""
from datetime import datetime

from src.db_connections.database import AsyncSessionLocal


async def record_model_call(**fields):
    from src.data_models.agents_model import AgentModelCalls

    # Own short session: the caller may be mid-transaction, and a failed workflow must still be observable.
    async with AsyncSessionLocal() as db:
        db.add(AgentModelCalls(**fields, created_at=datetime.utcnow()))
        await db.commit()
