import fakeredis
import pytest

from app.main import app
from app.ratelimit.dependency import get_rate_limiter
from app.ratelimit.token_bucket import TokenBucketRateLimiter


@pytest.fixture
def small_bucket():
    """
    Overrides the app's rate limiter with a small, fakeredis-backed,
    clock-controllable bucket for this test only — the standard FastAPI
    testing pattern (dependency_overrides), so these tests don't need a
    real Redis server.

    The fake clock is injected directly into the limiter (not via a global
    time.time() monkeypatch) because JWT expiry validation reads the real
    wall clock independently of time.time() — freezing time.time() globally
    would desync freshly-issued tokens from PyJWT's own expiry check and
    produce confusing 401s. See TokenBucketRateLimiter's docstring.
    """
    current_time = {"t": 1000.0}
    fake_redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    limiter = TokenBucketRateLimiter(
        capacity=2, refill_rate=1.0, redis_client=fake_redis, clock=lambda: current_time["t"]
    )
    app.dependency_overrides[get_rate_limiter] = lambda: limiter

    yield current_time  # tests can advance the fake clock via current_time["t"]

    app.dependency_overrides.pop(get_rate_limiter, None)


def _auth_headers(client, client_id: str) -> dict:
    token = client.post("/auth/token", json={"client_id": client_id}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_requests_within_capacity_are_allowed_with_headers(client, small_bucket):
    headers = _auth_headers(client, "client_a")

    r1 = client.get("/whoami", headers=headers)
    assert r1.status_code == 200
    assert r1.headers["X-RateLimit-Limit"] == "2"
    assert r1.headers["X-RateLimit-Remaining"] == "1"

    r2 = client.get("/whoami", headers=headers)
    assert r2.status_code == 200
    assert r2.headers["X-RateLimit-Remaining"] == "0"


def test_client_is_blocked_after_exceeding_capacity(client, small_bucket):
    headers = _auth_headers(client, "client_a")

    client.get("/whoami", headers=headers)  # 1/2
    client.get("/whoami", headers=headers)  # 2/2, bucket now empty

    blocked = client.get("/whoami", headers=headers)
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers
    assert int(blocked.headers["Retry-After"]) >= 1
    assert blocked.headers["X-RateLimit-Remaining"] == "0"


def test_client_is_unblocked_after_refill_window(client, small_bucket):
    headers = _auth_headers(client, "client_a")

    client.get("/whoami", headers=headers)  # 1/2
    client.get("/whoami", headers=headers)  # 2/2, empty
    still_blocked = client.get("/whoami", headers=headers)
    assert still_blocked.status_code == 429

    # advance the fake clock past the refill window (1 token/sec -> 2s is plenty)
    small_bucket["t"] += 2.0

    unblocked = client.get("/whoami", headers=headers)
    assert unblocked.status_code == 200


def test_rate_limits_are_isolated_per_client(client, small_bucket):
    a_headers = _auth_headers(client, "client_a")
    b_headers = _auth_headers(client, "client_b")

    client.get("/whoami", headers=a_headers)
    client.get("/whoami", headers=a_headers)
    a_blocked = client.get("/whoami", headers=a_headers)
    assert a_blocked.status_code == 429

    # client_b has never made a request — must not be affected by client_a's limit
    b_response = client.get("/whoami", headers=b_headers)
    assert b_response.status_code == 200
    assert b_response.headers["X-RateLimit-Remaining"] == "1"


def test_unauthenticated_request_is_401_not_429(client, small_bucket):
    # auth must be checked before rate limiting even runs (enforce_rate_limit
    # depends on get_current_client) — an unauthenticated request should
    # never consume a token from anyone's bucket.
    resp = client.get("/whoami")
    assert resp.status_code == 401
