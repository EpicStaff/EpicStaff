from typing import Optional

from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework_simplejwt.authentication import JWTAuthentication

from tables.models.rbac_models import ApiKey
from tables.services.rbac.api_key.authenticator import ApiKeyAuthenticator


class BearerAuthScheme(OpenApiAuthenticationExtension):
    target_class = "tables.services.rbac.authentication.JwtAuthentication"
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


class ApiKeyAuthScheme(OpenApiAuthenticationExtension):
    target_class = "tables.services.rbac.authentication.ApiKeyAuthentication"
    name = "ApiKeyAuth"

    def get_security_definition(self, auto_schema):
        return {"type": "apiKey", "in": "header", "name": "X-Api-Key"}


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


class JwtAuthentication(JWTAuthentication):
    """Bearer JWT authentication (simplejwt) with the project's 401 envelope.

    RFC 7235: a 401 response MUST include a WWW-Authenticate challenge.
    Without this override DRF may fall back to 403 for unauthenticated
    requests, contradicting the documented auth envelope.
    """

    def authenticate_header(self, request: Request) -> str:
        return "Bearer"


class ApiKeyAuthentication(BaseAuthentication):
    """X-Api-Key / `Authorization: ApiKey ...` authentication.

    `request.user` is the key owner (USER keys) or SystemServicePrincipal
    (SYSTEM keys); `request.auth` is the ApiKey instance so downstream code
    can distinguish key callers via `isinstance(request.auth, ApiKey)`.
    """

    _authenticator = ApiKeyAuthenticator()

    def authenticate_header(self, request: Request) -> str:
        return "Bearer"

    def authenticate(self, request: Request):
        raw_key = _get_api_key_from_headers(request)
        if not raw_key:
            return None
        return self._authenticator.authenticate(raw_key)


class JwtOrApiKeyAuthentication(BaseAuthentication):
    """
    Bearer JWT or X-Api-Key / `Authorization: ApiKey ...` authentication.

    Combines `JwtAuthentication` and `ApiKeyAuthentication` into a single
    authenticator for view/setting slots that need "one class, either
    credential type" (e.g. `DEFAULT_AUTHENTICATION_CLASSES` in test settings).
    Tries a Bearer JWT first, then falls back to API key resolution via
    `ApiKeyAuthenticator`.
    """

    _authenticator = ApiKeyAuthenticator()

    def __init__(self) -> None:
        self.jwt_auth = JWTAuthentication()

    def authenticate_header(self, request: Request) -> str:
        return "Bearer"

    def authenticate(self, request: Request):
        auth_header = _get_header(request, "HTTP_AUTHORIZATION")
        if auth_header and auth_header.lower().startswith("bearer "):
            return self.jwt_auth.authenticate(request)

        raw_key = _get_api_key_from_headers(request)
        if raw_key:
            return self._authenticator.authenticate(raw_key)

        return None


class IsAuthenticatedOrApiKey(BasePermission):
    """Allow requests authenticated by a valid ApiKey (including env-seeded
    system keys whose owner is AnonymousUser) or by a regular user session."""

    def has_permission(self, request, view) -> bool:
        if isinstance(request.auth, ApiKey):
            return True
        return bool(request.user and request.user.is_authenticated)
