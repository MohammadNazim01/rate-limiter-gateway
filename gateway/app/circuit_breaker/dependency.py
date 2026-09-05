from app.circuit_breaker.breaker import CircuitBreaker
from app.core.config import settings

_breaker: CircuitBreaker | None = None


def get_circuit_breaker() -> CircuitBreaker:
    """
    Provider function (not a hardcoded global), matching get_rate_limiter()
    and get_http_client() — so tests can override this via
    app.dependency_overrides with a breaker backed by a fake Redis and a
    controllable clock instead of needing a real Redis server.
    """
    global _breaker
    if _breaker is None:
        _breaker = CircuitBreaker(
            name="downstream_mock",
            failure_threshold=settings.BREAKER_FAILURE_THRESHOLD,
            cooldown_seconds=settings.BREAKER_COOLDOWN_SECONDS,
        )
    return _breaker
