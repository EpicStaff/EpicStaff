"""Audit tokens as django_app mints them, for calling the routes over HTTP."""

from datetime import datetime, timedelta, timezone

import jwt
from src.shared.audit.token import AUDIT_TOKEN_ISSUER

DEFAULT_CLAIMS = {
    "user_id": 42,
    "org_id": 7,
    "retention_days": 0,
    "AUDIT": ["read", "export"],
}


def make_token(**overrides) -> str:
    """A token as django_app mints it; an override of None drops that claim."""
    from app.core import settings

    now = datetime.now(timezone.utc)
    claims = {
        "iss": AUDIT_TOKEN_ISSUER,
        "iat": now,
        "exp": now + timedelta(seconds=300),
        **DEFAULT_CLAIMS,
        **overrides,
    }
    claims = {name: value for name, value in claims.items() if value is not None}
    return jwt.encode(claims, settings.AUDIT_JWT_SECRET, algorithm="HS256")


def auth(**overrides) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(**overrides)}"}
