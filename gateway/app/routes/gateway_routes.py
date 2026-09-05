from fastapi import APIRouter, Depends

from app.auth.dependency import get_current_client

router = APIRouter(tags=["gateway"])


@router.get("/whoami")
async def whoami(client_id: str = Depends(get_current_client)) -> dict:
    """
    Phase 1 diagnostic route: proves the combined JWT/API-key auth
    dependency works end-to-end. This will be replaced/extended once the
    actual rate-limited proxy route is built (Phase 3-4).
    """
    return {"client_id": client_id}
