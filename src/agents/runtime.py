"""
Process-wide agent runtime: checkpointer, compiled graph, tool executor, LLM router, runner and
(optionally) the in-process worker loop. Started and stopped by the FastAPI lifespan, or by the
dedicated worker (`python -m src.agents.worker`).
"""
import asyncio

from src.agents.checkpointer import Checkpointer
from src.agents.config import settings
from src.helpers.logging_config import get_logger

logger = get_logger("agents.runtime")


class AgentRuntime:
    def __init__(self):
        self.checkpointer: Checkpointer | None = None
        self.graph = None
        self.runner = None
        self.tools = None
        self.ready = False
        self.error: str | None = None
        self._worker: asyncio.Task | None = None
        self._stop: asyncio.Event | None = None

    async def start(self, *, worker: bool | None = None):
        if not settings().enabled:
            self.error = "AGENTS_ENABLED=false"
            return
        import src.agents.tools  # noqa: F401  (registers every tool)
        from src.agents.graph import build_graph
        from src.agents.llm import get_router
        from src.agents.runner import WorkflowRunner
        from src.agents.tools.base import ToolExecutor

        try:
            self.checkpointer = Checkpointer()
            saver = await self.checkpointer.open()
            self.graph = build_graph(saver)
            self.tools = ToolExecutor()
            get_router()  # load the registry now so configuration errors surface at startup
            self.runner = WorkflowRunner(self.graph, self.tools, get_router)
            self.ready, self.error = True, None
        except Exception as e:
            self.ready, self.error = False, f"{e.__class__.__name__}: {e}"[:300]
            logger.error(f"agent runtime unavailable: {self.error}")
            return
        run_worker = settings().worker_enabled if worker is None else worker
        if run_worker:
            from src.agents.worker import worker_loop

            self._stop = asyncio.Event()
            self._worker = asyncio.create_task(worker_loop(self, self._stop))

    async def stop(self):
        if self._stop:
            self._stop.set()
        if self._worker:
            await asyncio.gather(self._worker, return_exceptions=True)
        if self.runner:
            await self.runner.aclose()
        if self.checkpointer:
            await self.checkpointer.close()
        from src.agents.limits import limiter
        from src.agents.llm import close_router

        await close_router()
        await limiter.aclose()
        self.ready, self._worker, self._stop = False, None, None

    async def restart(self):
        """Tear down and rebuild everything (tests use this to prove runs survive a restart)."""
        await self.stop()
        await self.start()


runtime = AgentRuntime()
