import random

from locust import HttpUser, task, between


class GatewayUser(HttpUser):
    """
    Each simulated user is one distinct API client — gets its own JWT at
    start (via /auth/token), the same way a real client would identify
    itself to the gateway. wait_time keeps most individual clients within
    their own token-bucket allowance, so the load test measures realistic
    concurrent throughput and gateway latency rather than mostly
    generating 429s for a single hammering client.

    Two endpoints are measured separately:
      - /whoami:    gateway-only overhead (auth + rate limit + circuit
                    breaker check), no downstream call at all
      - /proxy/ok:  the full pipeline, including the forwarded call to the
                    downstream_mock service

    Comparing their p95/p99 isolates how much latency the gateway itself
    adds versus the downstream round-trip.
    """

    wait_time = between(0.5, 1.5)

    def on_start(self):
        client_id = f"loadtest-client-{random.randint(1, 1_000_000)}"
        resp = self.client.post(
            "/auth/token", json={"client_id": client_id}, name="/auth/token"
        )
        token = resp.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {token}"}

    @task(3)
    def whoami(self):
        self.client.get("/whoami", headers=self.headers, name="/whoami")

    @task(1)
    def proxy_ok(self):
        self.client.get("/proxy/ok", headers=self.headers, name="/proxy/ok")
