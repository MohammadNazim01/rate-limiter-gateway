# Phase 6 — Distributed Rate-Limit Proof (real docker-compose run)

**Setup:** `docker compose up --build --scale gateway=3 -d` — 3 independent gateway
containers, each with its own host port, all sharing one Redis instance and one
downstream_mock. Verified all healthy via `docker compose ps` before testing.

Host ports assigned by Docker for this run: gateway-1 → 39760, gateway-2 → 38116,
gateway-3 → 39804 (Redis and downstream_mock confirmed healthy alongside them).

**Test:** issued one JWT for a single client (`multi_instance_client`), then sent 30
requests to `/whoami` round-robin across all 3 gateway host ports (index i % 3),
with `RATE_LIMIT_CAPACITY=20` (default).

**Raw result:**
```
200(:39760) 200(:38116) 200(:39804) 200(:39760) 200(:38116) 200(:39804)
200(:39760) 200(:38116) 200(:39804) 200(:39760) 200(:38116) 200(:39804)
200(:39760) 200(:38116) 200(:39804) 200(:39760) 200(:38116) 200(:39804)
200(:39760) 200(:38116) 200(:39804) 200(:39760) 429(:38116) 429(:39804)
200(:39760) 429(:38116) 429(:39804) 429(:39760) 429(:38116) 429(:39804)

success=23 blocked=7 (out of 30)
```

**Why this is the correct proof, not just "it returned 200s":** if each of the 3
gateway instances tracked its own client state in local process memory (the
naive/broken approach this whole project exists to avoid), each instance would
independently allow its own ~20 requests before blocking — roughly 60 total
successes across 3 instances before any 429. Instead, blocking begins at request
~21-22 **total, across all three different ports simultaneously** — proving the
token-bucket state is correctly shared via Redis, not per-instance. The slightly
higher-than-20 success count (23) is expected and correct: `RATE_LIMIT_REFILL_RATE`
is 5 tokens/sec, and the loop's real wall-clock latency across 30 sequential curl
calls allowed a few tokens to refill mid-test — this is the token bucket behaving
exactly as designed, not a bug.

This is the empirical evidence for the "hardest problem #2" from the project plan:
*empirically proving distribution works*, not just asserting it.
