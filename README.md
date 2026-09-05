# Distributed Rate Limiter / API Gateway

![CI](https://github.com/MohammadNazim01/rate-limiter-gateway/actions/workflows/ci.yml/badge.svg)

A small FastAPI gateway that authenticates requests (JWT or API key),
enforces a **distributed, Redis-backed token-bucket rate limit** per client,
protects a downstream service behind a **circuit breaker**, and forwards
allowed requests through. "Distributed" is proven, not just claimed — see
[`docs/phase6_distributed_proof.md`](docs/phase6_distributed_proof.md) for a
real run across 3 concurrent gateway instances sharing one Redis.

## The problem

An API called by many clients needs protecting from any single client
overwhelming it — accidentally (a buggy retry loop) or on purpose. That gets
harder once the API runs as multiple instances behind a load balancer: if
each instance counts requests in its own memory, a client can get N× the
real limit by spreading requests across instances. This project builds a
correct, from-scratch solution to that — plus a circuit breaker so the
gateway fails fast instead of hammering a downstream that's already down.

## Architecture

```
        Locust / pytest / curl clients
        (each with its own API key or JWT)
                     |
                     v  HTTP
     +-------------------------------------------+
     |      API Gateway (FastAPI) — N instances     |
     |  1. Auth (JWT / API key)                     |
     |  2. Rate limit (Redis token bucket)          |
     |  3. Circuit breaker check                    |
     |  4. Forward (httpx -> downstream)            |
     +--------+-------------------------+-----------+
              |                         |
       (shared state)             (proxied request)
              v                         v
     +-----------------+     +---------------------------+
     |      Redis        |     |  Downstream Mock Service     |
     +-----------------+     +---------------------------+
```

Full component-by-component breakdown, why Redis backs the circuit breaker
too (not just the rate limiter), and the testing strategy (fakeredis +
one deliberate real-Redis smoke test) are in
[`docs/architecture.md`](docs/architecture.md).

## Why Token Bucket

Token Bucket is the implemented (V1) algorithm — each client has a bucket
with a max burst capacity and a steady refill rate, which is what most
real-world rate-limited APIs (Stripe, GitHub) actually use. It's implemented
behind a `RateLimiter` interface (`app/ratelimit/base.py`) specifically so
Sliding Window (a documented stretch goal — see the project plan) could be
added later as a second, swappable strategy rather than a rewrite. Fixed
Window was ruled out early: it has a well-known boundary-burst problem (2×
the limit right at a window edge), which is exactly the kind of thing a
from-scratch implementation should avoid rather than reproduce.

## Correctness, proven empirically — not just asserted

- **Atomicity under concurrency:** the entire check-and-consume is one
  Redis Lua script (`token_bucket.lua`), so two concurrent requests for the
  same client can't race on the starting token count. Verified with 50
  *truly parallel* requests (`xargs -P 50`, real OS-level concurrency, not
  paced/sequential) against the real running gateway + Redis: exactly 21
  succeeded for a capacity-20 bucket, not 30+ — see
  [`docs/loadtest_results.md`](docs/loadtest_results.md).
- **Distribution across instances:** 3 separate gateway containers, one
  shared Redis, one client's combined limit stays correct instead of
  tripling — see
  [`docs/phase6_distributed_proof.md`](docs/phase6_distributed_proof.md).
- **Circuit breaker state transitions**, including the single-trial
  guarantee when a cooldown expires under concurrent requests, are unit
  tested (`tests/unit/test_circuit_breaker.py`) and integration tested
  against the real `/proxy/flaky` endpoint
  (`tests/integration/test_circuit_breaker.py`).

## Load test results (real numbers)

40 concurrent simulated clients, 45s, against the real Docker stack — **0
failures across 1462 requests**:

| Endpoint | p50 | p95 | p99 |
|---|---|---|---|
| `/whoami` (gateway overhead only) | 9ms | 39ms | 74ms |
| `/proxy/ok` (full pipeline, incl. downstream) | 22ms | 91ms | 430ms |

Direct downstream call (bypassing the gateway): 2.3ms median — so the
gateway's own auth+rate-limit+breaker logic adds ~7ms p50, and forwarding
adds another ~13ms p50 on top. Full breakdown, raw CSVs, and honest
limitations (single laptop, dev-mode Uvicorn, not a dedicated benchmarking
rig) in [`docs/loadtest_results.md`](docs/loadtest_results.md).

## Running it locally

```bash
docker compose up --build -d
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready   # 200 once Redis is reachable

TOKEN=$(curl -s -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/json" -d '{"client_id":"me"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl http://localhost:8000/whoami -H "Authorization: Bearer $TOKEN"
curl http://localhost:8000/proxy/ok -H "Authorization: Bearer $TOKEN"
```

Prove the distributed claim yourself:
```bash
docker compose up --build --scale gateway=3 -d
docker compose port gateway 1   # repeat with 2, 3 for each replica's host port
# hit /whoami round-robin across all 3 ports with the same client's token —
# the combined limit stays correct instead of 3x'ing.
```

## Tests

```bash
cd gateway
pip install -r requirements.txt
pytest -v
```

45 tests (unit + integration), running against fakeredis by default so no
Docker is required; one file deliberately validates the real `.lua` scripts
against genuine Redis when it's reachable (auto-skipped otherwise — see
`docs/architecture.md`). CI (`.github/workflows/ci.yml`) runs the full suite
against a real `redis:7-alpine` service container on every push.

## What's deliberately not here

No UI (this is infrastructure, not a product — see `docs/architecture.md`
for the reasoning), no Sliding Window implementation yet (documented stretch
goal), no real key-management system, no production infra (VPC/IAM/
auto-scaling). See `docs/architecture.md`'s "What I'd do differently at
larger scale" section for the honest version of what's missing.

## Project layout

```
gateway/            FastAPI app: auth, ratelimit, circuit_breaker, proxy, routes
downstream_mock/     minimal FastAPI service the gateway proxies to (/ok, /flaky)
loadtest/            Locust scenario + real recorded results
docs/                architecture, distributed proof, load-test results
.github/workflows/   CI (pytest against a real Redis service container)
```
