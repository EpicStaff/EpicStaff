import secrets
from typing import Any

import jwt
from app.core import settings
from app.domains.base import AuditDomain
from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from src.shared.audit.token import AUDIT_TOKEN_ISSUER

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
    same AUDIT_JWT_SECRET - no callback to Django per request. Returns the
    decoded claims (user_id, org_id, retention_days, and one action list per
    resource).
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    try:
        return jwt.decode(
            credentials.credentials,
            settings.AUDIT_JWT_SECRET,
            algorithms=["HS256"],
            issuer=AUDIT_TOKEN_ISSUER,
            options={"require": ["exp", "iat", "iss", "org_id", "user_id"]},
        )
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid or expired token: {e}") from e


def _granted_actions(claims: dict, resource: str) -> list:
    granted = claims.get(resource, [])
    return granted if isinstance(granted, list) else []


def require_audit_action(domain: AuditDomain, action: str):
    """
    Dependency factory gating a domain's route on `action` being granted for
    that domain's own resource: the token carries one claim per resource,
    keyed by `domain.resource` (e.g. `{"AUDIT": ["read", "export"]}`), so a
    grant on one resource never opens another domain's routes.
    """

    async def _check(claims: dict = Depends(verify_user_jwt)) -> dict:
        if action not in _granted_actions(claims, domain.resource):
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
