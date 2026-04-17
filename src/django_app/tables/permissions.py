from typing import Iterable

from rest_framework.permissions import BasePermission


def _get_scopes_from_auth(auth) -> list[str]:
    if isinstance(auth, dict):
        scopes = auth.get("scopes", [])
        if isinstance(scopes, str):
            return [s for s in scopes.split() if s]
        if isinstance(scopes, list):
            return scopes
    return []


def _get_scopes_from_user(user) -> list[str]:
    if not user or not hasattr(user, "is_authenticated"):
        return []
    scopes = getattr(user, "scopes", None)
    if isinstance(scopes, list):
        return scopes
    return []


class HasScope(BasePermission):
    required_scopes: Iterable[str] = ()

    def __init__(self, *scopes: str):
        if scopes:
            self.required_scopes = scopes

    def has_permission(self, request, view):
        required = list(self.required_scopes)
        if not required:
            return True

        scopes = set(
            _get_scopes_from_auth(request.auth) + _get_scopes_from_user(request.user)
        )
        return all(scope in scopes for scope in required)
