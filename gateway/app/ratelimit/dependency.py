import math

from fastapi import Depends, HTTPException, Response, status

from app.auth.dependency import get_current_client
from app.core.config import settings
from app.ratelimit.base import RateLimiter
from app.ratelimit.token_bucket import TokenBucketRateLimiter

_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """
    Provider function (not a hardcoded global) so tests can swap in a
    limiter backed by a fake Redis via FastAPI's `app.dependency_overrides`,
    instead of needing a real Redis server for every integration test.
    """
    global _limiter
    if _limiter is None:
        _limiter = TokenBucketRateLimiter(
            capacity=settings.RATE_LIMIT_CAPACITY,
            refill_rate=settings.RATE_LIMIT_REFILL_RATE,
        )
    return _limiter


async def enforce_rate_limit(
    response: Response,
    client_id: str = Depends(get_current_client),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> str:
    """
    Runs the token-bucket check for the authenticated client and sets the
    rate-limit response headers. Raises 429 (with Retry-After) when the
    client is over their limit.

    Note on headers: we deliberately don't emit an X-RateLimit-Reset header.
    That header makes sense for fixed/sliding-window limiters (a single
    "window resets at T" instant) but doesn't map cleanly onto a
    continuously-refilling token bucket — Retry-After (seconds until at
    least one token is available) is the honest equivalent here.
    """
    result = await limiter.check(client_id)

    if not result.allowed:
        retry_after = max(1, math.ceil(result.retry_after))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limit exceeded",
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(result.limit),
                "X-RateLimit-Remaining": "0",
            },
        )

    response.headers["X-RateLimit-Limit"] = str(result.limit)
    response.headers["X-RateLimit-Remaining"] = str(result.remaining)
    return client_id
