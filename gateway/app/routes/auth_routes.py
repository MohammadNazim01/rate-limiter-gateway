from fastapi import APIRouter
from pydantic import BaseModel

from app.auth.jwt_auth import create_access_token
from app.core.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenRequest(BaseModel):
    client_id: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


@router.post("/token", response_model=TokenResponse)
async def issue_token(payload: TokenRequest) -> TokenResponse:
    """
    Demo-only token issuer. This project has no real client/user database,
    so any client_id is accepted here and a signed JWT is issued for it.
    In a real deployment this endpoint would sit behind its own
    authentication (e.g. a client secret) before issuing a token — that's
    intentionally out of scope for a rate-limiter/gateway project.
    """
    token = create_access_token(payload.client_id)
    return TokenResponse(access_token=token, expires_in=settings.JWT_EXPIRE_SECONDS)
