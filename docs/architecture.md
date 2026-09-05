# Architecture

## What this is

A small API gateway that sits in front of a downstream service and adds
three things a bare reverse proxy doesn't have: per-client authentication,
distributed rate limiting, and a circuit breaker around the downstream call.
"Distributed" is the operative word — every piece of shared state (rate-limit
buckets, breaker status) lives in Redis, not in any one gateway process's
memory, so the whole thing is correct no matter how many gateway instances
are running behind a load balancer.

## Request flow

```
        Locust / pytest / curl clients
        (each with its own API key or JWT)
                     |
                     v  HTTP
     +-------------------------------------------+
     |      API Gateway (FastAPI) — N instances     |
     |                                               |
     |  1. Auth      (JWT or X-API-Key)             |
     |  2. Rate limit  (Redis token bucket)         |
     |  3. Circuit breaker check (Redis 3-state)    |
     |  4. Forward     (httpx -> downstream)        |
     +--------+-------------------------+-----------+
              |                         |
       (shared state)             (proxied request)
              v                         v
     +-----------------+     +---------------------------+
     |      Redis        |     |  Downstream Mock Service     |
     | token-bucket state |     |  (FastAPI: /ok, /flaky)     |
     | breaker state      |     |  simulates a real backend     |
     +-----------------+     +---------------------------+
```

A request that fails auth never reaches the rate limiter. A request that's
over its rate limit never reaches the circuit breaker or the downstream call.
A request blocked by an open circuit breaker never actually calls downstream.
Each stage is a strict gate on the one after it — this is why the ordering
in `gateway_routes.py`'s dependency chain matters (`enforce_rate_limit`
depends on `get_current_client`; the breaker check happens before
`forward_request` inside the route body).

## Components

**Auth** (`app/auth/`) — `jwt_auth.py` issues/verifies HS256 JWTs (`sub`,
`iat`, `exp` claims, 15-minute default expiry); `api_key_auth.py` is a
simple static key→client_id lookup. `dependency.py`'s `get_current_client`
resolves whichever credential is actually present, validating it strictly
rather than silently falling back from an invalid JWT to API-key auth.

**Rate limiting** (`app/ratelimit/`) — Token Bucket is the implemented
strategy (`base.py` defines the `RateLimiter` interface so a second
algorithm, e.g. Sliding Window, could be added later without touching call
sites). The actual check-and-consume is one Redis Lua script
(`scripts/token_bucket.lua`) so the read, refill-math, and write happen
atomically — two concurrent requests for the same client can never race on
the starting token count. `TokenBucketRateLimiter` takes an injectable
Redis client and clock (see "Testing strategy" below for why the clock
specifically matters).

**Circuit breaker** (`app/circuit_breaker/`) — a Redis-backed 3-state
breaker (CLOSED → OPEN → HALF-OPEN), shared across instances for the same
reason the rate limiter is: one instance's failures should protect every
other instance, not just the one that happened to notice. The
single-trial-per-cooldown guarantee (`breaker_check.lua`) is the other
piece of code in this project (besides the token bucket) that has to be a
Lua script rather than Python: two requests arriving the instant a cooldown
expires must not both be treated as the recovery trial.

**Proxy/forwarding** (`app/proxy/`) — `forward_request()` uses one shared,
lazily-created `httpx.AsyncClient` (connection pooling reused across
requests) to call the downstream service, translating connection-level
failures into a distinct `DownstreamError` so the gateway can tell "the
downstream is unreachable" apart from "the downstream returned a normal
error response."

**Downstream mock** (`downstream_mock/`) — a minimal separate FastAPI app
(`/ok` always succeeds, `/flaky` fails a configurable fraction of the time)
that exists purely so the gateway has something real to proxy to and the
circuit breaker has something real to trip against, without depending on
any actual external service.

## Why Redis for the circuit breaker too, not just the rate limiter

It would be simpler to keep circuit-breaker state in each gateway process's
own memory — plenty of real systems do exactly that. The choice to make it
Redis-backed here is deliberate: it reuses the same atomicity lesson (Lua
scripts, single source of truth) in a second context, and it means N gateway
instances agree on whether the downstream is healthy instead of each one
independently re-learning it's down (and re-hammering it N times) before
converging.

## Testing strategy

Almost the entire suite runs against **fakeredis**, not a real Redis server,
specifically so development and most CI runs don't need Docker at all. The
one exception is deliberate: `tests/integration/test_real_redis_smoke.py`
runs the actual `.lua` scripts against a genuine Redis server to validate
that fakeredis's emulation is faithful — it's skipped (not failed) when no
real Redis is reachable, and runs for real in CI, where the GitHub Actions
workflow provides a real `redis:7-alpine` service container.

A related, non-obvious lesson from building this: JWT expiry validation
(PyJWT) reads the real wall clock via `datetime.now(timezone.utc)`, not
`time.time()`. Early versions of the rate-limiter tests monkeypatched
`time.time()` globally to control the token-bucket's clock deterministically
— which silently broke JWT expiry checks in the same tests, since PyJWT
never looked at the patched value. The fix was to make the rate limiter and
circuit breaker take an **injectable clock parameter** instead of reading
the global clock at all, so tests control exactly the code that needs
controlling and nothing else.

## What's deliberately out of scope for this project

- **No UI.** This is infrastructure, not a product — real API gateways
  (Kong, Envoy, AWS API Gateway's core proxy layer) don't have end-user UIs
  either. The README, architecture docs, and load-test results are the
  presentation layer.
- **No Sliding Window implementation yet** (stretch goal) — the
  `RateLimiter` interface exists specifically to make adding one later a
  contained change, not a rewrite.
- **No real key-management system** — API keys are a static lookup, not
  issuance/rotation/revocation.
- **No production infra (VPC/IAM/auto-scaling)** — this project proves the
  gateway logic is correct and measures its overhead; it isn't a deployment
  of it.

## What I'd do differently at larger scale

- Run the gateway with gunicorn + multiple Uvicorn workers instead of a
  single dev-mode process — the load test's p99 tail on the proxied path
  (see `docs/loadtest_results.md`) is consistent with single-process
  contention, not the rate-limiter/breaker logic itself.
- Put a real load balancer (nginx/Envoy) in front instead of manually
  discovering each Docker-assigned host port to prove distribution, as
  Phase 6 did.
- For a much higher request volume than this project was built to test,
  I'd look at whether a single Redis instance becomes the bottleneck and
  consider Redis Cluster or client-side sharding by client_id — the Lua
  scripts here don't assume a single-node Redis, but the current setup
  doesn't exercise that path.
