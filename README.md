# Distributed Rate Limiter / API Gateway

![CI](https://github.com/MohammadNazim01/rate-limiter-gateway/actions/workflows/ci.yml/badge.svg)

**Status: Phase 8 done** (auth, token-bucket rate limiting, proxy/forwarding,
circuit breaker, multi-instance Docker, Locust load test, and CI all verified
— see `docs/`). Full architecture write-up gets finished in Phase 9.

- `docs/phase6_distributed_proof.md` — 3-instance shared-limit proof
- `docs/loadtest_results.md` — real Locust p95/p99 numbers

## Local dev
```
docker compose up --build -d
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready   # 200 once Redis is reachable
curl http://localhost:9000/health

# issue a token and call the gateway
TOKEN=$(curl -s -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/json" -d '{"client_id":"me"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl http://localhost:8000/whoami -H "Authorization: Bearer $TOKEN"
curl http://localhost:8000/proxy/ok -H "Authorization: Bearer $TOKEN"
```

## Prove distributed rate limiting (3 gateway instances, 1 shared limit)
```
docker compose up --build --scale gateway=3 -d
docker compose port gateway 1   # repeat with 2, 3 for each replica's host port
# hit /whoami round-robin across all 3 ports with the same client's token —
# the combined limit stays correct instead of 3x'ing. See docs/phase6_distributed_proof.md
# for a captured real run.
```

## Tests
```
cd gateway
pip install -r requirements.txt
pytest -v
```
