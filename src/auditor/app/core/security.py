import secrets
from typing import Any

import jwt
from app.core import settings
from app.domains.base import AuditDomain
from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_bearer_scheme = HTTPBearer(auto_error=False)


async def verify_ingest_api_key(
    api_key: str | None = Security(_api_key_header),
) -> None:
    """
    FastAPI dependency gating the ingest endpoint. Compares the presented
    X-API-Key against AUDITOR_INGEST_API_KEY using a constant-time
    comparison to avoid a timing side-channel on the check itself.
    """
    if api_key is None or not secrets.compare_digest(api_key, settings.AUDITOR_INGEST_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


async def verify_user_jwt(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """
    FastAPI dependency gating query/export routes. Decodes the short-lived
    JWT minted by django_app's POST /api/audit/token/ locally with the
    same JWT_SECRET - no callback to Django per request. Returns the
    decoded claims (org_id, actions, retention_days).
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    try:
        return jwt.decode(credentials.credentials, settings.JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid or expired token: {e}") from e


def require_audit_action(domain: AuditDomain, action: str):
    """
    Dependency factory: read vs export are independently gated by the
    token's `actions` claim. Use Depends(require_audit_action(domain, "read"))
    on query routes, Depends(require_audit_action(domain, "export")) on
    export routes. `domain.resource` (not a hardcoded "AUDIT" literal)
    names the resource reported in the 403 detail, so a second domain with
    a different `resource` value is reported correctly.

    TODO: the check below is still a flat `action in claims["actions"]`
    with no resource dimension - it does not actually restrict a token to
    `domain.resource`. A token with "read" passes this check on every
    registered domain's routes, not just the one its `resource` was granted
    for. Closing this needs a cross-layer change: Django's audit token
    (src/django_app/tables/views/audit_token_views.py) would need to emit a
    resource-keyed claim (e.g. {"AUDIT": ["read","export"]}) instead of a
    flat action list, and this check would need to look up
    claims[domain.resource] instead of claims["actions"]. Out of scope while
    only one domain ("sessions") is registered - no user-facing gap today.
    """

    async def _check(claims: dict = Depends(verify_user_jwt)) -> dict:
        if action not in claims.get("actions", []):
            raise HTTPException(
                status_code=403,
                detail=f"Missing {domain.resource}:{action} permission",
            )

        if "retention_days" not in claims:
            raise HTTPException(
                status_code=401,
                detail="Token missing retention_days claim",
            )
        return claims

    return _check
