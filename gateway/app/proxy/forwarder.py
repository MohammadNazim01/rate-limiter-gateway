import httpx

from app.core.config import settings

_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """
    Lazily creates one shared httpx.AsyncClient for the process (connection
    pooling/keep-alive reused across requests, instead of opening a fresh
    connection per proxied call). Exposed as a provider function — like
    get_redis() and get_rate_limiter() — so tests can override it with a
    client wired to httpx.MockTransport instead of hitting a real downstream
    service over the network.
    """
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=settings.DOWNSTREAM_TIMEOUT_SECONDS)
    return _client


class DownstreamError(Exception):
    """
    Raised when the downstream call fails outright — connection refused,
    DNS failure, timeout. Deliberately distinct from the downstream
    returning a normal (even 4xx/5xx) HTTP response, which is just data to
    forward back to the original client, not a gateway-level failure.
    """


async def forward_request(
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    params: dict | None = None,
    content: bytes | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> httpx.Response:
    """Forwards one request to the downstream service and returns its raw
    response. Raises DownstreamError for connection-level failures."""
    client = http_client if http_client is not None else get_http_client()
    base = settings.DOWNSTREAM_BASE_URL.rstrip("/")
    url = f"{base}/{path.lstrip('/')}"

    try:
        return await client.request(
            method, url, headers=headers, params=params, content=content
        )
    except httpx.RequestError as exc:
        raise DownstreamError(f"downstream call to {url} failed: {exc}") from exc
