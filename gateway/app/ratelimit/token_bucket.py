import time
from pathlib import Path

from app.core.redis_client import get_redis
from app.ratelimit.base import RateLimiter, RateLimitResult

_SCRIPT_SOURCE = (Path(__file__).parent / "scripts" / "token_bucket.lua").read_text()


class TokenBucketRateLimiter(RateLimiter):
    """
    Redis-backed, atomic token-bucket limiter. Correct across any number of
    gateway instances because all state lives in Redis, not process memory —
    the entire check-and-consume happens inside one Lua script (EVAL), so
    there's no read-then-write window for two concurrent requests to race.

    `redis_client` is injected (not hardcoded to the global connection pool)
    so tests can pass in a fake/in-memory Redis instead of a real server.
    """

    def __init__(
        self,
        capacity: int,
        refill_rate: float,
        redis_client=None,
        key_prefix: str = "ratelimit:token_bucket",
    ):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.key_prefix = key_prefix
        self._redis = redis_client if redis_client is not None else get_redis()
        self._script = self._redis.register_script(_SCRIPT_SOURCE)

    async def check(self, client_id: str, cost: int = 1) -> RateLimitResult:
        key = f"{self.key_prefix}:{client_id}"
        now = time.time()

        raw_allowed, raw_tokens, raw_retry_after = await self._script(
            keys=[key],
            args=[self.capacity, self.refill_rate, now, cost],
        )

        return RateLimitResult(
            allowed=bool(int(raw_allowed)),
            remaining=int(float(raw_tokens)),  # floored — never over-report headroom
            limit=self.capacity,
            retry_after=round(float(raw_retry_after), 3),
        )
