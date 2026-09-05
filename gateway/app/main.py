import logging

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core import redis_client
from app.routes import auth_routes, gateway_routes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gateway")

app = FastAPI(
    title="Distributed Rate Limiter / API Gateway",
    version="0.1.0",
    docs_url="/docs" if settings.ENVIRONMENT == "development" else None,
)

app.include_router(auth_routes.router)
app.include_router(gateway_routes.router)


@app.get("/health/live", tags=["health"])
async def health_live():
    """Liveness: the process is up. No external dependencies checked —
    this is what a load balancer/orchestrator polls to know 'don't kill me'."""
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def health_ready():
    """Readiness: can this instance actually serve traffic right now?
    Checks Redis, since rate limiting (and later, circuit-breaker state)
    depend on it. Returns 503 instead of 200 when Redis is unreachable —
    that's the correct signal for an orchestrator to stop routing here."""
    redis_ok = await redis_client.ping()
    if not redis_ok:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "redis": "unreachable"},
        )
    return {"status": "ready", "redis": "ok"}
