from fastapi import APIRouter, Depends

from app.ratelimit.dependency import enforce_rate_limit

router = APIRouter(tags=["gateway"])


@router.get("/whoami")
async def whoami(client_id: str = Depends(enforce_rate_limit)) -> dict:
    """
    Diagnostic route: proves auth + rate limiting end-to-end. Depending on
    `enforce_rate_limit` (which itself depends on `get_current_client`)
    means this route is authenticated AND rate-limited per client, with
    X-RateLimit-* headers set on the response. Will be replaced/extended
    once the actual downstream-proxy route is built (Phase 4).
    """
    return {"client_id": client_id}
