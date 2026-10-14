"""
Durable LangGraph checkpoints in PostgreSQL (langgraph-checkpoint-postgres, AsyncPostgresSaver).

The saver uses its own psycopg 3 pool whose search_path is CHECKPOINT_SCHEMA (default
"langgraph", created by migration 006), so its tables never mix with business tables and
Alembic never manages them. Create/upgrade them as an explicit deploy step:

    python -m src.agents.checkpointer setup        (also run by ./entrypoint.sh migrate)

AGENT_CHECKPOINTER=memory uses LangGraph's in-memory saver: development only - paused
workflows are lost on restart.
"""
import asyncio
import os
import sys

from dotenv import load_dotenv

from src.agents.config import settings
from src.helpers.logging_config import get_logger

logger = get_logger(__name__)


def conninfo() -> str:
    from psycopg.conninfo import make_conninfo

    cfg = settings()
    load_dotenv()
    options = f"-c search_path={cfg.checkpoint_schema}"
    if cfg.checkpoint_db_url:
        return make_conninfo(cfg.checkpoint_db_url, options=options)
    return make_conninfo(
        host=os.getenv("POSTGRES_HOST"), port=os.getenv("POSTGRES_DB_INTERNAL_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB"), user=os.getenv("POSTGRES_USER"), password=os.getenv("POSTGRES_PASSWORD"),
        application_name="smart-agri-tech-checkpoints", options=options,
    )


class Checkpointer:
    def __init__(self):
        self.saver = None
        self._pool = None

    async def open(self):
        if settings().checkpointer == "memory":
            from langgraph.checkpoint.memory import InMemorySaver

            logger.warning("AGENT_CHECKPOINTER=memory: paused workflows will not survive a restart")
            self.saver = InMemorySaver()
            return self.saver
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        self._pool = AsyncConnectionPool(
            conninfo(), min_size=1, max_size=int(os.getenv("CHECKPOINT_POOL_SIZE", "10")), open=False,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        )
        await self._pool.open(wait=True, timeout=15)
        self.saver = AsyncPostgresSaver(self._pool)
        return self.saver

    async def setup(self):
        if self.saver is None:
            await self.open()
        if hasattr(self.saver, "setup"):
            await self.saver.setup()

    async def close(self):
        if self._pool is not None:
            await self._pool.close()
        self._pool = self.saver = None


async def _setup() -> int:
    checkpointer = Checkpointer()
    try:
        await checkpointer.setup()
        print(f"LangGraph checkpoint tables are ready in schema '{settings().checkpoint_schema}'.")
        return 0
    finally:
        await checkpointer.close()


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] != "setup":
        print("usage: python -m src.agents.checkpointer setup")
        raise SystemExit(2)
    if sys.platform == "win32":  # psycopg's async mode needs the selector loop on Windows
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(asyncio.run(_setup()))
