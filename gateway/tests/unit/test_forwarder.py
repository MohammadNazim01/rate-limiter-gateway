import httpx
import pytest

from app.proxy.forwarder import DownstreamError, forward_request


def _client_with_handler(handler) -> httpx.AsyncClient:
    """httpx's built-in MockTransport — no extra mocking library needed,
    no real network call, and no dependency on the downstream_mock service
    actually running during tests."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_forward_request_builds_correct_url_and_returns_response():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        return httpx.Response(200, json={"message": "ok"})

    client = _client_with_handler(handler)
    resp = await forward_request("GET", "/ok", http_client=client)

    assert resp.status_code == 200
    assert resp.json() == {"message": "ok"}
    assert seen["method"] == "GET"
    assert seen["url"].endswith("/ok")


async def test_forward_request_passes_through_headers_params_and_body():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["params"] = dict(request.url.params)
        seen["body"] = request.content
        return httpx.Response(201)

    client = _client_with_handler(handler)
    resp = await forward_request(
        "POST",
        "/echo",
        headers={"X-Client-Id": "client_a"},
        params={"q": "1"},
        content=b'{"hello":"world"}',
        http_client=client,
    )

    assert resp.status_code == 201
    assert seen["headers"]["x-client-id"] == "client_a"
    assert seen["params"] == {"q": "1"}
    assert seen["body"] == b'{"hello":"world"}'


async def test_forward_request_leading_slash_normalization():
    from app.core.config import settings

    expected = f"{settings.DOWNSTREAM_BASE_URL.rstrip('/')}/flaky"
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200)

    client = _client_with_handler(handler)
    # both with and without a leading slash on `path` should hit the same URL
    resp = await forward_request("GET", "flaky", http_client=client)
    assert resp.status_code == 200
    assert seen["url"] == expected


async def test_forward_request_downstream_http_error_status_is_not_raised():
    # A 500 from downstream is just data — not a gateway-level failure.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    client = _client_with_handler(handler)
    resp = await forward_request("GET", "/flaky", http_client=client)
    assert resp.status_code == 500


async def test_forward_request_connection_failure_raises_downstream_error():
    def handler(request: httpx.Request):
        raise httpx.ConnectError("connection refused", request=request)

    client = _client_with_handler(handler)
    with pytest.raises(DownstreamError):
        await forward_request("GET", "/ok", http_client=client)


async def test_forward_request_timeout_raises_downstream_error():
    def handler(request: httpx.Request):
        raise httpx.TimeoutException("timed out", request=request)

    client = _client_with_handler(handler)
    with pytest.raises(DownstreamError):
        await forward_request("GET", "/flaky", http_client=client)
