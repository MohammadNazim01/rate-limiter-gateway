import httpx
from fastapi import APIRouter, Depends, Request, Response, status

from app.proxy.forwarder import DownstreamError, forward_request, get_http_client
from app.ratelimit.dependency import enforce_rate_limit

router = APIRouter(tags=["gateway"])

# Headers that are meaningful only for a single hop and must not be blindly
# copied from the incoming request to the downstream call, or from the
# downstream response back to the original client (e.g. copying the
# downstream's Content-Length verbatim could mismatch bytes we re-serialize).
_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


def _strip_hop_by_hop(headers) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() not in _HOP_BY_HOP_HEADERS}


@router.get("/whoami")
async def whoami(client_id: str = Depends(enforce_rate_limit)) -> dict:
    """
    Diagnostic route: proves auth + rate limiting end-to-end without
    involving the downstream service at all.
    """
    return {"client_id": client_id}


@router.api_route(
    "/proxy/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def proxy(
    path: str,
    request: Request,
    response: Response,
    client_id: str = Depends(enforce_rate_limit),
    http_client: httpx.AsyncClient = Depends(get_http_client),
) -> Response:
    """
    The actual gateway route: authenticate -> rate-limit -> forward to the
    downstream service -> return its response. (Circuit breaker around the
    forward_request call is added in Phase 5 — right now a downstream
    failure just returns 503 directly.)
    """
    body = await request.body()

    try:
        downstream_response = await forward_request(
            method=request.method,
            path=path,
            headers=_strip_hop_by_hop(request.headers),
            params=dict(request.query_params),
            content=body,
            http_client=http_client,
        )
    except DownstreamError:
        final = Response(
            content='{"detail":"downstream service unavailable"}',
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            media_type="application/json",
        )
        # carry over the rate-limit headers enforce_rate_limit already set
        # on the shared `response` object for this request
        for k, v in response.headers.items():
            final.headers[k] = v
        return final

    final = Response(
        content=downstream_response.content,
        status_code=downstream_response.status_code,
        headers=_strip_hop_by_hop(downstream_response.headers),
        media_type=downstream_response.headers.get("content-type"),
    )
    for k, v in response.headers.items():
        final.headers[k] = v
    return final
