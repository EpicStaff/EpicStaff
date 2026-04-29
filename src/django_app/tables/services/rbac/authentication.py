from typing import Optional, Tuple

from django.contrib.auth.models import AnonymousUser
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request
from rest_framework_simplejwt.authentication import JWTAuthentication

from tables.models.rbac_models import ApiKey


class JwtOrApiKeyAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "tables.services.rbac.authentication.JwtOrApiKeyAuthentication"
    name = "BearerAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "oauth2",
            "flows": {
                "password": {
                    "tokenUrl": "/api/auth/swagger-token/",
                    "scopes": {},
                }
            },
        }


def _get_header(request: Request, name: str) -> Optional[str]:
    value = request.META.get(name)
    if value:
        return value
    return None


def _get_api_key_from_headers(request: Request) -> Optional[str]:
    header = _get_header(request, "HTTP_X_API_KEY")
    if header:
        return header.strip()

    auth = _get_header(request, "HTTP_AUTHORIZATION")
    if not auth:
        return None

    if auth.lower().startswith("apikey "):
        return auth.split(" ", 1)[1].strip()

    return None


class JwtOrApiKeyAuthentication(BaseAuthentication):
    """
    Bearer JWT or X-Api-Key / `Authorization: ApiKey ...` authentication.

    For API keys, `request.user` resolves to the key's owning User (or
    AnonymousUser for env-seeded keys with no `created_by`). `request.auth` is
    the ApiKey instance, so downstream code can still inspect key scopes and
    distinguish key vs. JWT callers via `isinstance(request.auth, ApiKey)`.
    """

    def __init__(self) -> None:
        self.jwt_auth = JWTAuthentication()

    def authenticate_header(self, request: Request) -> str:
        # RFC 7235: a 401 response MUST include a WWW-Authenticate challenge.
        # Without this method DRF falls back to 403 for unauthenticated
        # requests, which contradicts the documented auth envelope and makes
        # it harder for clients to distinguish "no creds" from "forbidden".
        return "Bearer"

    def authenticate(self, request: Request) -> Optional[Tuple[object, object]]:
        auth_header = _get_header(request, "HTTP_AUTHORIZATION")
        if auth_header and auth_header.lower().startswith("bearer "):
            return self.jwt_auth.authenticate(request)

        api_key = _get_api_key_from_headers(request)
        if api_key:
            return self._authenticate_api_key(api_key)

        return None

    def _authenticate_api_key(self, api_key: str) -> Tuple[object, ApiKey]:
        prefix = api_key[:8]
        keys = ApiKey.objects.filter(
            prefix=prefix, revoked_at__isnull=True
        ).select_related("created_by")
        for key in keys:
            if key.check_key(api_key):
                key.mark_used()
                owner = key.created_by or AnonymousUser()
                return owner, key

        raise AuthenticationFailed("Invalid API key")
