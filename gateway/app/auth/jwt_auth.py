import time

import jwt

from app.core.config import settings


class InvalidTokenError(Exception):
    """Raised for any JWT problem — bad signature, expired, or malformed."""


def create_access_token(client_id: str) -> str:
    """Issues a signed JWT for client_id. Same reasoning as the Boboloo
    token lifetime: short expiry bounds the blast radius of a leaked token,
    since a stateless JWT can't be cheaply revoked before it naturally expires."""
    now = int(time.time())
    payload = {
        "sub": client_id,
        "iat": now,
        "exp": now + settings.JWT_EXPIRE_SECONDS,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> str:
    """Verifies signature + expiry and returns the client_id (sub claim).
    Raises InvalidTokenError for any failure — callers decide the HTTP status."""
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    return payload["sub"]
