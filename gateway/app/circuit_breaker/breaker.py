import time as _time_module
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.core.redis_client import get_redis

_CHECK_SCRIPT = (Path(__file__).parent / "scripts" / "breaker_check.lua").read_text()
_RECORD_SCRIPT = (Path(__file__).parent / "scripts" / "breaker_record.lua").read_text()


@dataclass
class BreakerCheckResult:
    allowed: bool
    state: str  # "closed" | "open" | "half_open" (half_open is transient — see breaker_check.lua)


class CircuitBreaker:
    """
    Redis-backed 3-state circuit breaker (CLOSED -> OPEN -> HALF-OPEN),
    shared across all gateway instances so they agree on whether a
    downstream service is healthy — one instance's failures immediately
    protect every other instance too, instead of each instance
    independently re-hammering a dead downstream before learning it's down.

    `redis_client` and `clock` are both injected, same reasoning as
    TokenBucketRateLimiter: tests need a fake Redis and a controllable
    clock without monkeypatching time.time() globally (see that class's
    docstring for why the global monkeypatch approach breaks JWT tests).
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int,
        cooldown_seconds: float,
        redis_client=None,
        clock: Callable[[], float] = _time_module.time,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._redis = redis_client if redis_client is not None else get_redis()
        self._check_script = self._redis.register_script(_CHECK_SCRIPT)
        self._record_script = self._redis.register_script(_RECORD_SCRIPT)
        self._clock = clock
        self._key = f"circuitbreaker:{name}"

    async def check(self) -> BreakerCheckResult:
        """Call before attempting the downstream call. If not allowed, skip
        the call entirely (fail fast) — do not call record_* in that case."""
        allowed, state = await self._check_script(
            keys=[self._key], args=[self._clock(), self.cooldown_seconds]
        )
        return BreakerCheckResult(allowed=bool(int(allowed)), state=state)

    async def record_success(self) -> str:
        """Call after a downstream call that check() allowed succeeded."""
        return await self._record_script(
            keys=[self._key], args=[1, self._clock(), self.failure_threshold]
        )

    async def record_failure(self) -> str:
        """Call after a downstream call that check() allowed failed
        (connection error, timeout, or a 5xx response)."""
        return await self._record_script(
            keys=[self._key], args=[0, self._clock(), self.failure_threshold]
        )
