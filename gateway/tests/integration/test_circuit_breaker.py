import fakeredis
import httpx
import pytest

from app.circuit_breaker.breaker import CircuitBreaker
from app.circuit_breaker.dependency import get_circuit_breaker
from app.main import app
from app.proxy.forwarder import get_http_client


@pytest.fixture
def flaky_setup():
    """
    A low-threshold, clock-controllable breaker plus a downstream mock
    whose behavior we can flip between "always fails" and "always
    succeeds" mid-test — this is what lets us deterministically drive the
    breaker through every state without relying on the real downstream
    mock's random FLAKY_FAILURE_RATE.
    """
    current_time = {"t": 1000.0}
    fake_redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    breaker = CircuitBreaker(
        name="downstream_mock",
        failure_threshold=3,
        cooldown_seconds=10.0,
        redis_client=fake_redis,
        clock=lambda: current_time["t"],
    )
    app.dependency_overrides[get_circuit_breaker] = lambda: breaker

    downstream_should_fail = {"value": True}
    call_count = {"value": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["value"] += 1
        if downstream_should_fail["value"]:
            return httpx.Response(500, json={"detail": "simulated downstream failure"})
        return httpx.Response(200, json={"message": "ok"})

    fake_http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app.dependency_overrides[get_http_client] = lambda: fake_http_client

    yield {
        "time": current_time,
        "downstream_should_fail": downstream_should_fail,
        "call_count": call_count,
    }

    app.dependency_overrides.pop(get_circuit_breaker, None)
    app.dependency_overrides.pop(get_http_client, None)


def _auth_headers(client, client_id="client_a") -> dict:
    token = client.post("/auth/token", json={"client_id": client_id}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_breaker_opens_after_threshold_failures_via_flaky_endpoint(client, flaky_setup):
    headers = _auth_headers(client)

    # 3 consecutive 500s from /proxy/flaky trip the breaker (threshold=3)
    for _ in range(3):
        resp = client.get("/proxy/flaky", headers=headers)
        assert resp.status_code == 500  # downstream's real error, forwarded as-is

    assert flaky_setup["call_count"]["value"] == 3

    # 4th call: breaker is now open — must be rejected WITHOUT calling downstream
    blocked = client.get("/proxy/flaky", headers=headers)
    assert blocked.status_code == 503
    assert "circuit breaker is open" in blocked.json()["detail"]
    assert flaky_setup["call_count"]["value"] == 3  # unchanged — downstream was never called


def test_breaker_recovers_after_cooldown_when_downstream_heals(client, flaky_setup):
    headers = _auth_headers(client)

    for _ in range(3):
        client.get("/proxy/flaky", headers=headers)  # trip the breaker

    blocked = client.get("/proxy/flaky", headers=headers)
    assert blocked.status_code == 503

    # downstream "heals" and the cooldown window passes
    flaky_setup["downstream_should_fail"]["value"] = False
    flaky_setup["time"]["t"] += 10.0

    # this is the half-open trial — it must actually reach the downstream
    trial = client.get("/proxy/flaky", headers=headers)
    assert trial.status_code == 200
    assert flaky_setup["call_count"]["value"] == 4  # the trial did call downstream

    # breaker is closed again — normal traffic flows
    normal = client.get("/proxy/flaky", headers=headers)
    assert normal.status_code == 200
    assert flaky_setup["call_count"]["value"] == 5


def test_breaker_reopens_if_the_half_open_trial_also_fails(client, flaky_setup):
    headers = _auth_headers(client)

    for _ in range(3):
        client.get("/proxy/flaky", headers=headers)

    flaky_setup["time"]["t"] += 10.0  # cooldown elapses, downstream still failing

    trial = client.get("/proxy/flaky", headers=headers)
    assert trial.status_code == 500  # the trial itself reached downstream and failed
    assert flaky_setup["call_count"]["value"] == 4

    # immediately after the failed trial, breaker must be open again
    still_blocked = client.get("/proxy/flaky", headers=headers)
    assert still_blocked.status_code == 503
    assert flaky_setup["call_count"]["value"] == 4  # not called again


def test_client_side_4xx_from_downstream_does_not_trip_breaker(client, flaky_setup):
    # a 4xx is the client's fault, not the downstream's — should not count
    # as a breaker failure. Simulate by pointing at a route the mock
    # transport treats as "not flaky failing" but still non-2xx: reuse the
    # same handler with a 4xx by checking call_count instead of relying on
    # a separate path — here we directly assert via record semantics using
    # the real proxy but a controlled 404-style response.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "not found"})

    app.dependency_overrides[get_http_client] = lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )
    headers = _auth_headers(client)

    for _ in range(5):  # well past the threshold=3, if 4xx counted as failure
        resp = client.get("/proxy/anything", headers=headers)
        assert resp.status_code == 404

    # breaker must still be closed — a 6th call should still reach downstream
    still_reaches_downstream = client.get("/proxy/anything", headers=headers)
    assert still_reaches_downstream.status_code == 404
