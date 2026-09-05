import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.circuit_breaker.breaker import CircuitBreaker
from app.circuit_breaker.dependency import get_circuit_breaker
from app.main import app
from app.ratelimit.dependency import get_rate_limiter
from app.ratelimit.token_bucket import TokenBucketRateLimiter


@pytest.fixture
def client():
    """
    A single TestClient used via `with`, so all HTTP calls made inside one
    test share one persistent anyio portal/event loop. Without the `with`,
    a module-level `TestClient(app)` can end up running different calls on
    different event loops — harmless for a test that touches Redis at most
    once, but fakeredis's async primitives bind to whichever loop was
    running on their *first* use, so a second call on a different loop
    raises "Queue is bound to a different event loop". Any test that calls
    a Redis-backed endpoint more than once needs this fixture.
    """
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def default_rate_limiter():
    """
    Every test gets a generous, fakeredis-backed rate limiter by default, so
    tests that aren't specifically about rate-limiting (e.g. the Phase 1
    auth tests) don't need a real Redis server and don't get accidentally
    blocked. Tests that want to exercise real rate-limiting behavior (see
    tests/integration/test_rate_limit.py) override this again with their
    own small-capacity limiter — that override wins for the duration of
    those tests since it's applied after this one.
    """
    fake_redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    limiter = TokenBucketRateLimiter(
        capacity=1000, refill_rate=1000.0, redis_client=fake_redis
    )
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    yield
    app.dependency_overrides.pop(get_rate_limiter, None)


@pytest.fixture(autouse=True)
def default_circuit_breaker():
    """
    Every test gets a fresh, fakeredis-backed circuit breaker by default
    (always CLOSED, never tripped), same reasoning as default_rate_limiter.
    Tests that want to exercise real breaker state transitions (see
    tests/integration/test_circuit_breaker.py) override this again with
    their own low-threshold breaker.
    """
    fake_redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    breaker = CircuitBreaker(
        name="test", failure_threshold=1000, cooldown_seconds=1000.0, redis_client=fake_redis
    )
    app.dependency_overrides[get_circuit_breaker] = lambda: breaker
    yield
    app.dependency_overrides.pop(get_circuit_breaker, None)
