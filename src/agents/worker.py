"""
Agent worker loop: drives queued runs, recovers runs whose lease expired (crashed worker),
wakes runs whose counterparty acted, and expires stale approvals.

Runs inside the API process by default (AGENT_WORKER_ENABLED=true). For larger deployments set
it to false on the API and run dedicated workers - any number is safe, because runs are claimed
with leases:

    python -m src.agents.worker        (or ./entrypoint.sh agent-worker)
"""
import asyncio
import sys

from sqlalchemy.exc import SQLAlchemyError

from src.agents.config import settings
from src.helpers.logging_config import get_logger

logger = get_logger("agents.worker")


async def tick(rt) -> dict:
    runner = rt.runner
    return {
        "expired_approvals": await runner.expire_approvals(),
        "woken": await runner.wake_external(),
        "driven": await runner.process_queue(),
    }


async def worker_loop(rt, stop: asyncio.Event):
    interval = settings().worker_poll_s
    logger.info(f"agent worker started (every {interval}s)")
    while not stop.is_set():
        try:
            result = await tick(rt)
            if any(result.values()):
                logger.info("agent worker tick", extra=result)
        except SQLAlchemyError as e:
            logger.error(f"agent worker tick failed: {e.__class__.__name__}")
        except Exception as e:
            logger.exception(f"agent worker tick failed: {e}")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


async def _main():
    import src.data_models.registry  # noqa: F401
    from src.agents.runtime import runtime

    await runtime.start(worker=False)
    if not runtime.ready:
        logger.error(f"agent runtime failed to start: {runtime.error}")
        return 1
    stop = asyncio.Event()
    try:
        await worker_loop(runtime, stop)
    finally:
        await runtime.stop()
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(asyncio.run(_main()))
