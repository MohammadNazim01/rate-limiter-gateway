import os
import random
import time

from fastapi import FastAPI, HTTPException

app = FastAPI(title="Downstream Mock Service", version="0.1.0")

# Controllable via env so tests/Locust can dial failure behavior without
# code changes — used later (Phase 5) to trip the circuit breaker on purpose.
FLAKY_FAILURE_RATE = float(os.getenv("FLAKY_FAILURE_RATE", "0.5"))
FLAKY_DELAY_SECONDS = float(os.getenv("FLAKY_DELAY_SECONDS", "0"))


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ok")
async def ok():
    """Always succeeds — the 'happy path' downstream call."""
    return {"message": "downstream call succeeded", "ts": time.time()}


@app.get("/flaky")
async def flaky():
    """Fails FLAKY_FAILURE_RATE of the time (default 50%) and can be made
    slow via FLAKY_DELAY_SECONDS — used to exercise the circuit breaker."""
    if FLAKY_DELAY_SECONDS:
        time.sleep(FLAKY_DELAY_SECONDS)
    if random.random() < FLAKY_FAILURE_RATE:
        raise HTTPException(status_code=500, detail="simulated downstream failure")
    return {"message": "downstream call succeeded (flaky endpoint)", "ts": time.time()}
