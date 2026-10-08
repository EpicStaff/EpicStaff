import os

# The auditor settings module requires these at import time (no defaults) -
# set dummy values before anything under app.* gets imported, so this module
# is runnable on its own without a real .env file (mirrors what docker-compose injects).
os.environ.setdefault("OPENSEARCH_PASSWORD", "test")
os.environ.setdefault("AUDITOR_INGEST_API_KEY", "test-ingest-key")
os.environ.setdefault("AUDIT_JWT_SECRET", "test-secret")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_USER", "test")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_PASSWORD", "")
os.environ.setdefault("AUDITOR_REDIS_DB", "1")

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core import security, settings
from src.shared.audit.token import AUDIT_TOKEN_ISSUER


def _make_token(**overrides) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "iss": AUDIT_TOKEN_ISSUER,
        "user_id": 1,
        "org_id": 7,
        "AUDIT": ["read"],
        "retention_days": 0,
        "iat": now,
        "exp": now + timedelta(seconds=300),
    }
    payload.update(overrides)
    for key, value in list(payload.items()):
        if value is None:
            del payload[key]
    return jwt.encode(payload, settings.AUDIT_JWT_SECRET, algorithm="HS256")


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


@pytest.mark.asyncio
async def test_valid_token_is_accepted():
    claims = await security.verify_user_jwt(_creds(_make_token()))
    assert claims["org_id"] == 7


@pytest.mark.asyncio
async def test_wrong_issuer_is_rejected():
    with pytest.raises(HTTPException):
        await security.verify_user_jwt(_creds(_make_token(iss="someone-else")))


@pytest.mark.asyncio
async def test_missing_issuer_is_rejected():
    with pytest.raises(HTTPException):
        await security.verify_user_jwt(_creds(_make_token(iss=None)))


@pytest.mark.asyncio
async def test_missing_expiry_is_rejected():
    with pytest.raises(HTTPException):
        await security.verify_user_jwt(_creds(_make_token(exp=None)))
