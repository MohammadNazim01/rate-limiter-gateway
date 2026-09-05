import fakeredis
import pytest

from app.ratelimit.token_bucket import TokenBucketRateLimiter


def make_limiter(capacity=3, refill_rate=1.0, clock=None):
    """Fresh fake Redis + limiter per test — no shared state between tests,
    and no real Redis server required (see project plan: fakeredis lets these
    run in plain CI without a Redis service container). `clock` is injected
    directly into the limiter rather than monkeypatching time.time() globally
    — see TokenBucketRateLimiter's docstring for why that matters."""
    fake_redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    kwargs = {}
    if clock is not None:
        kwargs["clock"] = clock
    limiter = TokenBucketRateLimiter(
        capacity=capacity, refill_rate=refill_rate, redis_client=fake_redis, **kwargs
    )
    return limiter


async def test_first_request_on_fresh_bucket_is_allowed():
    limiter = make_limiter(capacity=3, refill_rate=1.0)
    result = await limiter.check("client_a")
    assert result.allowed is True
    assert result.remaining == 2  # capacity 3, consumed 1
    assert result.limit == 3
    assert result.retry_after == 0


async def test_bucket_empties_after_capacity_requests_then_denies():
    limiter = make_limiter(capacity=3, refill_rate=1.0, clock=lambda: 1000.0)

    r1 = await limiter.check("client_a")
    r2 = await limiter.check("client_a")
    r3 = await limiter.check("client_a")
    assert (r1.allowed, r2.allowed, r3.allowed) == (True, True, True)
    assert r3.remaining == 0

    r4 = await limiter.check("client_a")
    assert r4.allowed is False
    assert r4.remaining == 0
    assert r4.retry_after > 0


async def test_denied_request_does_not_consume_a_token():
    limiter = make_limiter(capacity=1, refill_rate=1.0, clock=lambda: 2000.0)

    first = await limiter.check("client_a")
    assert first.allowed is True

    # bucket is now empty; the next two calls should both be denied with the
    # same remaining=0 — a denied call must not silently drain more tokens
    second = await limiter.check("client_a")
    third = await limiter.check("client_a")
    assert second.allowed is False
    assert third.allowed is False
    assert second.remaining == 0 == third.remaining


async def test_tokens_refill_over_time():
    current_time = {"t": 5000.0}
    limiter = make_limiter(capacity=3, refill_rate=1.0, clock=lambda: current_time["t"])

    await limiter.check("client_a")  # 3 -> 2
    await limiter.check("client_a")  # 2 -> 1
    await limiter.check("client_a")  # 1 -> 0
    denied = await limiter.check("client_a")
    assert denied.allowed is False

    # advance the fake clock by 2 seconds -> 2 tokens should have refilled
    current_time["t"] += 2.0
    allowed_after_refill = await limiter.check("client_a")
    assert allowed_after_refill.allowed is True
    assert allowed_after_refill.remaining == 1  # 2 refilled, minus 1 consumed now


async def test_refill_never_exceeds_capacity():
    current_time = {"t": 9000.0}
    limiter = make_limiter(capacity=3, refill_rate=1.0, clock=lambda: current_time["t"])

    await limiter.check("client_a")  # consume 1 -> 2 remaining

    # advance the clock by a huge amount — bucket must cap at capacity, not overflow
    current_time["t"] += 10_000
    result = await limiter.check("client_a")
    assert result.allowed is True
    assert result.remaining == 2  # was capped at 3, minus the 1 just consumed


async def test_retry_after_reflects_refill_rate():
    limiter = make_limiter(capacity=1, refill_rate=2.0, clock=lambda: 1000.0)  # 0.5s/token

    await limiter.check("client_a")  # consumes the only token
    denied = await limiter.check("client_a")
    assert denied.allowed is False
    assert denied.retry_after == pytest.approx(0.5, abs=0.01)


async def test_different_clients_have_independent_buckets():
    limiter = make_limiter(capacity=1, refill_rate=1.0, clock=lambda: 1000.0)

    a = await limiter.check("client_a")
    b = await limiter.check("client_b")
    assert a.allowed is True
    assert b.allowed is True  # client_b's bucket is independent, not shared with client_a
