import httpx
import pytest

from app.main import app
from app.proxy.forwarder import get_http_client


@pytest.fixture
def mock_downstream():
    """
    Overrides get_http_client with a client wired to httpx.MockTransport,
    so /proxy/* tests exercise the real gateway route (auth, rate limit,
    forwarding, header handling) without needing the actual downstream_mock
    process running — same dependency_overrides pattern used for Redis.
    """
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/flaky":
            return httpx.Response(500, json={"detail": "simulated downstream failure"})
        return httpx.Response(
            200,
            json={"message": "downstream call succeeded"},
            headers={"X-Downstream-Marker": "yes"},
        )

    fake_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app.dependency_overrides[get_http_client] = lambda: fake_client

    yield calls

    app.dependency_overrides.pop(get_http_client, None)


def _auth_headers(client, client_id="client_a") -> dict:
    token = client.post("/auth/token", json={"client_id": client_id}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_proxy_forwards_request_and_returns_downstream_response(client, mock_downstream):
    headers = _auth_headers(client)
    resp = client.get("/proxy/ok", headers=headers)

    assert resp.status_code == 200
    assert resp.json() == {"message": "downstream call succeeded"}
    assert resp.headers["x-downstream-marker"] == "yes"
    # gateway's own rate-limit headers must still be present on a proxied response
    assert "x-ratelimit-limit" in resp.headers


def test_proxy_forwards_downstream_error_status_as_is(client, mock_downstream):
    headers = _auth_headers(client)
    resp = client.get("/proxy/flaky", headers=headers)

    assert resp.status_code == 500
    assert resp.json() == {"detail": "simulated downstream failure"}


def test_proxy_requires_authentication(client, mock_downstream):
    resp = client.get("/proxy/ok")
    assert resp.status_code == 401


def test_proxy_forwards_query_params_and_method(client, mock_downstream):
    headers = _auth_headers(client)
    resp = client.post("/proxy/ok?foo=bar", headers=headers, json={"x": 1})
    assert resp.status_code == 200

    sent_request = mock_downstream[-1]
    assert sent_request.method == "POST"
    assert dict(sent_request.url.params) == {"foo": "bar"}


def test_proxy_is_rate_limited_like_any_other_route(client, mock_downstream):
    # uses the default (generous) fakeredis limiter from conftest.py — this
    # just proves /proxy/* goes through enforce_rate_limit too, not that
    # it has separate limiting logic (that's already covered by
    # test_rate_limit.py against /whoami).
    headers = _auth_headers(client)
    resp = client.get("/proxy/ok", headers=headers)
    assert "x-ratelimit-remaining" in resp.headers
