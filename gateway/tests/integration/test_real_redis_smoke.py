"""
The rest of this test suite deliberately uses fakeredis (see conftest.py and
every other test file) so that development and most CI don't require a real
Redis server. That's a real assumption worth validating, though: fakeredis
is a Redis *emulator*, not Redis itself, and Lua/EVAL behavior in particular
is exactly the kind of thing that could subtly differ.

This file is the check on that assumption — it runs the real
TokenBucketRateLimiter (and its real .lua script) against an actual Redis
server. It's automatically skipped when no real Redis is reachable (e.g.
local development without `docker compose up`), and runs for real in CI,
where the GitHub Actions workflow provides a genuine Redis service
container specifically so this file has something to test against.
"""

import os

import pytest
import redis as sync_redis
import redis.asyncio as redis

from app.ratelimit.token_bucket import TokenBucketRateLimiter

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _real_redis_reachable() -> bool:
    try:
        client = sync_redis.Redis.from_url(REDIS_URL, socket_connect_timeout=1)
        return bool(client.ping())
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _real_redis_reachable(),
    reason=(
        f"no real Redis reachable at {REDIS_URL} — expected when developing "
        "without `docker compose up` or outside CI; this smoke test exists "
        "specifically to validate fakeredis's fidelity when a real Redis IS "
        "available, not to require one everywhere."
    ),
)


@pytest.fixture
async def real_redis_client():
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    yield client
    await client.flushdb()  # leave the shared CI Redis instance clean
    await client.aclose()


async def test_token_bucket_lua_script_against_real_redis(real_redis_client):
    limiter = TokenBucketRateLimiter(
        capacity=2,
        refill_rate=1.0,
        redis_client=real_redis_client,
        clock=lambda: 1000.0,
    )

    first = await limiter.check("real_redis_smoke_client")
    second = await limiter.check("real_redis_smoke_client")
    third = await limiter.check("real_redis_smoke_client")

    assert (first.allowed, second.allowed, third.allowed) == (True, True, False)
    assert third.retry_after > 0


async def test_token_bucket_refill_against_real_redis():
    current_time = {"t": 2000.0}
    real_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        limiter = TokenBucketRateLimiter(
            capacity=1,
            refill_rate=2.0,  # 0.5s per token
            redis_client=real_client,
            clock=lambda: current_time["t"],
        )
        await limiter.check("real_redis_refill_client")  # consumes the only token
        denied = await limiter.check("real_redis_refill_client")
        assert denied.allowed is False

        current_time["t"] += 1.0  # well past the 0.5s refill window
        allowed_after_refill = await limiter.check("real_redis_refill_client")
        assert allowed_after_refill.allowed is True
    finally:
        await real_client.flushdb()
        await real_client.aclose()
