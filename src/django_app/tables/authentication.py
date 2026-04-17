from typing import Optional, Tuple

from django.utils import timezone
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request
from rest_framework_simplejwt.authentication import JWTAuthentication

from tables.models.auth_models import ApiKey


class JwtOrApiKeyAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "tables.authentication.JwtOrApiKeyAuthentication"
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
    def __init__(self) -> None:
        self.jwt_auth = JWTAuthentication()

    def authenticate(self, request: Request) -> Optional[Tuple[object, object]]:
        auth_header = _get_header(request, "HTTP_AUTHORIZATION")
        if auth_header and auth_header.lower().startswith("bearer "):
            return self.jwt_auth.authenticate(request)

        api_key = _get_api_key_from_headers(request)
        if api_key:
            return self._authenticate_api_key(api_key)

        return None

    def _authenticate_api_key(self, api_key: str) -> Tuple[object, object]:
        prefix = api_key[:8]
        keys = ApiKey.objects.filter(prefix=prefix, revoked_at__isnull=True)
        for key in keys:
            if key.check_key(api_key):
                key.last_used_at = timezone.now()
                key.save(update_fields=["last_used_at"])
                return key, {"scopes": key.scopes}

        raise AuthenticationFailed("Invalid API key")
