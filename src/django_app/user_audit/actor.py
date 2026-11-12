from dataclasses import dataclass

from django.contrib.auth import get_user_model
from plugins.ownership.request_scope import current_principal
from rbac.identity.api_keys.principals import SystemServicePrincipal
from rbac.models import ApiKey


@dataclass(frozen=True)
class Actor:
    """Who took an action: a user, or the system API key (no user, empty email)."""

    user_id: int | None
    email: str
    api_key_name: str | None


def actor_from_request(request) -> Actor | None:
    """Return who made the request, or None when nobody a user-action record names did.

    Works on the HttpRequest as well as on DRF's Request: DRF copies `user` and `auth`
    onto the HttpRequest once it authenticates. None for an anonymous caller, a plugin's
    service account (its activity is recorded by the plugin platform) and any other
    principal that is neither a user nor the system API key.
    """
    if current_principal() is not None:
        return None
    api_key = getattr(request, "auth", None)
    api_key_name = api_key.name if isinstance(api_key, ApiKey) else None
    user = getattr(request, "user", None)
    if isinstance(user, SystemServicePrincipal):
        return Actor(user_id=None, email="", api_key_name=api_key_name)
    if isinstance(user, get_user_model()):
        return Actor(user_id=user.pk, email=user.email, api_key_name=api_key_name)
    return None
