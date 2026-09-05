from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int       # tokens left after this request (floored) — X-RateLimit-Remaining
    limit: int           # bucket capacity — X-RateLimit-Limit
    retry_after: float   # seconds until at least one token is available (0 if allowed)


class RateLimiter(ABC):
    """
    Common interface so the gateway can swap rate-limiting algorithms
    (Token Bucket now, Sliding Window later — see project plan Part 6)
    without touching the code that calls it.
    """

    @abstractmethod
    async def check(self, client_id: str, cost: int = 1) -> RateLimitResult:
        """Atomically checks and, if allowed, consumes `cost` units of the
        client's quota. Must never leave the shared state in a state where
        two concurrent callers can both succeed past the limit."""
        raise NotImplementedError
