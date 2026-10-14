"""
Abuse controls for the agent layer: workflow starts per minute and model calls per hour, per user.

Without REDIS_URL the limits are per process (like src/core/rate_limit.py). With REDIS_URL they
are shared by every worker and replica, which matters here because model calls cost money.
A Redis outage degrades to the in-process limiter rather than blocking users.
"""
import time

from fastapi import HTTPException, status

from src.agents.config import settings
from src.core.rate_limit import SlidingWindowLimiter, rate_limiting_enabled
from src.helpers.logging_config import get_logger

logger = get_logger(__name__)


class Limiter:
    def __init__(self):
        self._local = SlidingWindowLimiter()
        self._redis = None
        self._redis_checked = False

    def _redis_client(self):
        if not self._redis_checked:
            self._redis_checked = True
            url = settings().redis_url
            if url:
                try:
                    import redis.asyncio as redis

                    self._redis = redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)
                except ImportError:
                    logger.warning("REDIS_URL is set but the redis package is not installed; using in-process limits")
        return self._redis

    async def allow(self, key: str, limit: int, window_s: int) -> bool:
        if not rate_limiting_enabled() or limit <= 0:
            return True
        client = self._redis_client()
        if client is not None:
            bucket = f"agents:rl:{key}:{int(time.time() // window_s)}"
            try:
                count = await client.incr(bucket)
                if count == 1:
                    await client.expire(bucket, window_s + 1)
                return count <= limit
            except Exception as e:
                logger.warning(f"Redis rate limiter unavailable ({e.__class__.__name__}); using in-process limits")
        return self._local.allow(key, limit, window_s)

    def reset(self):
        self._local.reset()

    async def aclose(self):
        if self._redis is not None:
            await self._redis.aclose()
        self._redis, self._redis_checked = None, False


limiter = Limiter()


async def check_workflow_start(user_id: int):
    if not await limiter.allow(f"wf:{user_id}", settings().workflow_starts_per_minute, 60):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="Too many assistant requests. Please wait a minute and try again.")


async def llm_quota_ok(user_id: int) -> bool:
    return await limiter.allow(f"llm:{user_id}", settings().llm_calls_per_hour, 3600)
