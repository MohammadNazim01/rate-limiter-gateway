# Distributed Rate Limiter / API Gateway

**Status: Phase 0 — scaffolding.** This README is a placeholder; it gets fully written in Phase 9 with real architecture docs and load-test results. See `docs/` (added later) for the project plan.

## Local dev (once Docker Desktop WSL integration is enabled)
```
docker compose up --build
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
curl http://localhost:9000/health
```
