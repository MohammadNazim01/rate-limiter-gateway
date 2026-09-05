from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central config. All values are overridable via environment variables
    (or a local .env file, which is gitignored) — never hardcode secrets here.
    """

    ENVIRONMENT: str = "development"

    # Redis (shared rate-limit + circuit-breaker state)
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    JWT_SECRET: str = "dev-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_SECONDS: int = 900  # 15 minutes — same reasoning as Boboloo's token lifetime

    # API keys: simple demo lookup, format "key1:client1,key2:client2".
    # Not a real key-management system on purpose — see Part 6 of the project plan.
    API_KEYS_RAW: str = "demo-key-123:demo-client"

    # Downstream service this gateway proxies to
    DOWNSTREAM_BASE_URL: str = "http://localhost:9000"
    DOWNSTREAM_TIMEOUT_SECONDS: float = 5.0

    # Token bucket defaults (per-client, can later be made per-route/per-tier)
    RATE_LIMIT_CAPACITY: int = 20      # max burst tokens
    RATE_LIMIT_REFILL_RATE: float = 5  # tokens added per second

    # Circuit breaker defaults
    BREAKER_FAILURE_THRESHOLD: int = 5     # consecutive failures before opening
    BREAKER_COOLDOWN_SECONDS: int = 30     # how long OPEN lasts before HALF-OPEN trial

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
