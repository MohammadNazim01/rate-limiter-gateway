import time

import jwt
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)


def test_issue_token_returns_jwt():
    resp = client.post("/auth/token", json={"client_id": "client_a"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.JWT_EXPIRE_SECONDS
    assert len(body["access_token"].split(".")) == 3  # header.payload.signature


def test_whoami_without_credentials_is_401():
    resp = client.get("/whoami")
    assert resp.status_code == 401


def test_whoami_with_valid_jwt_returns_client_id():
    token = client.post("/auth/token", json={"client_id": "client_a"}).json()["access_token"]
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == {"client_id": "client_a"}


def test_whoami_with_malformed_jwt_is_401():
    resp = client.get("/whoami", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401


def test_whoami_with_expired_jwt_is_401():
    now = int(time.time())
    expired_payload = {"sub": "client_a", "iat": now - 1000, "exp": now - 1}
    expired_token = jwt.encode(
        expired_payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM
    )
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {expired_token}"})
    assert resp.status_code == 401


def test_whoami_with_valid_api_key_returns_client_id():
    # "demo-key-123:demo-client" is the default seeded in Settings.API_KEYS_RAW
    resp = client.get("/whoami", headers={"X-API-Key": "demo-key-123"})
    assert resp.status_code == 200
    assert resp.json() == {"client_id": "demo-client"}


def test_whoami_with_invalid_api_key_is_401():
    resp = client.get("/whoami", headers={"X-API-Key": "not-a-real-key"})
    assert resp.status_code == 401


def test_jwt_takes_priority_when_both_credentials_present_but_jwt_is_invalid():
    # If a Bearer token is present, it must be validated on its own terms —
    # an invalid JWT should not silently fall back to API-key auth.
    resp = client.get(
        "/whoami",
        headers={"Authorization": "Bearer garbage", "X-API-Key": "demo-key-123"},
    )
    assert resp.status_code == 401
