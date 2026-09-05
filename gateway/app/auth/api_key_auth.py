from app.core.config import settings


class InvalidApiKeyError(Exception):
    """Raised when an API key doesn't match any known client."""


def _parse_api_keys(raw: str) -> dict[str, str]:
    keys: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        key, client_id = pair.split(":", 1)
        keys[key.strip()] = client_id.strip()
    return keys


# Parsed once at import time from settings. This is deliberately a simple
# static lookup, not a real key-management system (issuance/rotation/revocation) —
# see Part 6 of the project plan for what's in/out of scope for V1.
_API_KEYS = _parse_api_keys(settings.API_KEYS_RAW)


def resolve_api_key(api_key: str) -> str:
    """Returns the client_id for a valid API key, or raises InvalidApiKeyError."""
    client_id = _API_KEYS.get(api_key)
    if client_id is None:
        raise InvalidApiKeyError("unknown API key")
    return client_id
