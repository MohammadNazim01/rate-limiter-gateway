import redis.asyncio as redis

from app.core.config import settings

# A single connection pool for the process. Created lazily (not at import
# time) so the app can boot even if Redis isn't reachable yet — individual
# endpoints that actually need Redis will surface a clear error instead of
# the whole app failing to start.
_pool: redis.ConnectionPool | None = None


def get_redis() -> redis.Redis:
    global _pool
    if _pool is None:
        _pool = redis.ConnectionPool.from_url(
            settings.REDIS_URL, decode_responses=True
        )
    return redis.Redis(connection_pool=_pool)


async def ping() -> bool:
    """Used by the /health/ready check — returns False instead of raising
    so a Redis outage shows up as a normal 'not ready' response, not a 500."""
    try:
        client = get_redis()
        return await client.ping()
    except Exception:
        return False
