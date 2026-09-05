import httpx
from fastapi import APIRouter, Depends, Request, Response, status

from app.circuit_breaker.breaker import CircuitBreaker
from app.circuit_breaker.dependency import get_circuit_breaker
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


def _with_rate_limit_headers(final: Response, response: Response) -> Response:
    for k, v in response.headers.items():
        final.headers[k] = v
    return final


@router.get("/whoami")
async def whoami(client_id: str = Depends(enforce_rate_limit)) -> dict:
    """
    Diagnostic route: proves auth + rate limiting end-to-end without
    involving the downstream service (or the circuit breaker) at all.
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
    breaker: CircuitBreaker = Depends(get_circuit_breaker),
) -> Response:
    """
    The full gateway pipeline: authenticate -> rate-limit -> circuit-breaker
    check -> forward to downstream -> record the outcome -> return the
    response.

    A downstream response with status >= 500 counts as a breaker failure,
    same as a connection error — a downstream that's up but returning 500s
    is just as unhealthy from the gateway's point of view. A 4xx is treated
    as the client's fault, not the downstream's, and does not count against
    the breaker.
    """
    check = await breaker.check()
    if not check.allowed:
        return _with_rate_limit_headers(
            Response(
                content='{"detail":"downstream circuit breaker is open"}',
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                media_type="application/json",
            ),
            response,
        )

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
        await breaker.record_failure()
        return _with_rate_limit_headers(
            Response(
                content='{"detail":"downstream service unavailable"}',
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                media_type="application/json",
            ),
            response,
        )

    if downstream_response.status_code >= 500:
        await breaker.record_failure()
    else:
        await breaker.record_success()

    final = Response(
        content=downstream_response.content,
        status_code=downstream_response.status_code,
        headers=_strip_hop_by_hop(downstream_response.headers),
        media_type=downstream_response.headers.get("content-type"),
    )
    return _with_rate_limit_headers(final, response)
