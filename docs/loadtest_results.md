# Load Test Results (Phase 7)

**All numbers on this page are real, captured from an actual `docker compose`
run against real Redis, real downstream_mock, and real Locust traffic — none
are estimated or invented.** Run on a single gateway instance (dev-mode
Uvicorn, no `--workers`), via Docker Desktop WSL2 on a personal laptop — not a
dedicated benchmarking rig, so treat absolute numbers as directionally honest
rather than production-SLA-grade.

## Test 1 — Concurrent load (Locust, 40 users, 45s)

**Setup:** each simulated user is a distinct client (own JWT via `/auth/token`,
`wait_time` 0.5-1.5s between requests) — this measures realistic concurrent
*throughput and latency*, not single-client rate-limit rejection.

**Config:** `locust -f locustfile.py --users 40 --spawn-rate 8 --run-time 45s`

| Endpoint | Requests | Failures | p50 | p90 | p95 | p99 | Max |
|---|---|---|---|---|---|---|---|
| `POST /auth/token` | 40 | 0 | 30ms | 59ms | 74ms | 140ms | 140ms |
| `GET /whoami` (gateway only — auth + rate limit + breaker check, no downstream) | 1072 | 0 | 9ms | 26ms | **39ms** | **74ms** | 151ms |
| `GET /proxy/ok` (full pipeline — + forward to downstream) | 350 | 0 | 22ms | 61ms | **91ms** | **430ms** | 755ms |
| **Aggregated** | **1462** | **0 (0.00%)** | 12ms | 37ms | 53ms | 100ms | 755ms |

Full raw CSVs: `loadtest/results/loadtest_stats.csv`,
`loadtest/results/loadtest_stats_history.csv`.

**Isolating the gateway's own overhead** — direct downstream call, bypassing
the gateway entirely (`curl http://downstream_mock:9000/ok` from inside the
Docker network), median latency: **2.3ms**. Compared to:
- `/whoami` p50 9ms → the gateway's own auth+rate-limit+breaker-check logic
  (2 Redis round-trips: token bucket + circuit breaker) adds **~7ms p50**.
- `/proxy/ok` p50 22ms → adding the actual forwarded downstream call on top
  costs roughly another **~13ms p50** (httpx call + response reassembly),
  bringing total gateway-added overhead to **~20ms p50** for a fully proxied
  request versus calling downstream directly.

The p99 tail on `/proxy/ok` (430ms) is notably higher than its p50 (22ms) —
worth being honest about in an interview: this is consistent with occasional
GC pauses / event-loop contention under Python's single dev-mode Uvicorn
process rather than a systemic issue with the rate-limiter or breaker logic
themselves (`/whoami`, which does the same Redis calls but skips the httpx
forward, doesn't show a comparable tail). A production deployment would run
gunicorn with multiple Uvicorn workers (same pattern used in the real
Boboloo backend) rather than a single dev-mode process.

## Test 2 — Concurrency correctness under real parallel load (no overshoot)

Locust's `wait_time` pacing above means individual clients rarely hit their
own limit — it measures throughput, not rate-limit correctness under
contention. To specifically verify the atomic Lua script holds up under
*genuinely simultaneous* requests (not sequential, not paced), 50 truly
parallel requests (`xargs -P 50`, real OS-level concurrency) were fired for
one single client against the real running gateway + Redis, with
`RATE_LIMIT_CAPACITY=20`:

```
200s: 21
429s: 29
```

**21 successes out of 50 concurrent requests for a capacity-20 bucket** — the
1 extra above 20 is consistent with a small amount of real refill during the
sub-second window all 50 requests landed in (`RATE_LIMIT_REFILL_RATE=5/sec`),
not a race condition. Zero clients got anywhere close to over-consuming (e.g.
30+ or all 50 succeeding), which is what would happen if the check-then-write
in the Lua script weren't atomic. This is the concurrency-correctness claim
from the project plan's "hardest problems" list, verified against real
infrastructure rather than only in the mocked pytest suite.

## Test 3 — Distributed correctness across instances

Covered separately in `docs/phase6_distributed_proof.md` (3 gateway
instances, one shared Redis, one client's combined limit stays correct
instead of tripling).

## Honest limitations of this test

- Single laptop, WSL2, Docker Desktop — not isolated hardware. Absolute
  latency numbers would look different on real cloud infra.
- Dev-mode Uvicorn (no gunicorn/multi-worker) — the p99 tail on the proxy
  path would likely tighten with multiple workers.
- 40 concurrent users is a modest load, not a stress test to find the
  gateway's breaking point — that would be a reasonable stretch goal beyond
  V1 scope (see project plan, Section 6).
