from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.api_key_auth import InvalidApiKeyError, resolve_api_key
from app.auth.jwt_auth import InvalidTokenError, decode_access_token

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_client(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> str:
    """
    Resolves the authenticated client_id from either a Bearer JWT or an
    X-API-Key header.

    Deliberately NOT a silent fallback chain: whichever credential is
    actually present gets validated strictly, and an invalid one fails
    immediately with 401 rather than being treated as "absent" and falling
    through to the other method — that would quietly mask real auth errors.
    """
    if credentials is not None:
        try:
            return decode_access_token(credentials.credentials)
        except InvalidTokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid or expired token",
            )

    if x_api_key is not None:
        try:
            return resolve_api_key(x_api_key)
        except InvalidApiKeyError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid API key",
            )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="missing credentials — provide a Bearer token or X-API-Key header",
    )
