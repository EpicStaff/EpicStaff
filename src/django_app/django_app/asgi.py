"""
ASGI config for django_app project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/asgi/
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_app.settings")

# Must be called before any app code is imported to avoid AppRegistryNotReady.
from django.core.asgi import get_asgi_application

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from plugins.ownership.request_scope import PluginRequestScopeASGI
from rbac.models.enums import ResourceType
from tables.graph_collab.ws_auth import TicketAuthMiddleware
from tables.views.storage_upload_stream_view import (
    UPLOAD_STREAM_ACTION,
    UPLOAD_STREAM_PATH,
    upload_stream_app,
)
from tables.views.storage_views import StorageAPIView
from tables.views.transfer_import_upload_view import IMPORT_JOB_ROUTES, import_upload_app
from user_audit.middleware import UserActionASGI

from django_app.forwarding_headers import DropUnderscoreForwardingHeadersMiddleware
from django_app.routing import websocket_urlpatterns

# The streamed uploads bypass Django's middleware, so a plugin service account's request
# gets its request scope (ownership of what it creates, the activity event) here instead, and
# a user's upload to storage its user-action context and record. Nested in the same order as
# MIDDLEWARE.
upload_stream = PluginRequestScopeASGI(
    UserActionASGI(
        upload_stream_app,
        view_class=StorageAPIView,
        action=UPLOAD_STREAM_ACTION,
        route=UPLOAD_STREAM_PATH.lstrip("/"),
    ),
    resource_type=ResourceType.FILES.value,
    route=UPLOAD_STREAM_PATH.lstrip("/"),
)
# Raw ASGI apps by exact path: each reads its request body itself, as it arrives.
raw_http_apps = {
    UPLOAD_STREAM_PATH: upload_stream,
    **{
        route.path: PluginRequestScopeASGI(
            import_upload_app(route),
            resource_type=route.resource_type.value,
            route=route.path.lstrip("/"),
        )
        for route in IMPORT_JOB_ROUTES
    },
}


def canonical_path(path: str) -> str:
    """The path as nginx normalises it to choose a location: runs of `/` merged, `.` and `..`
    segments resolved, a trailing `/` kept. nginx forwards the original spelling, so a request
    for `//api/x` reaches here as sent; the raw apps are looked up by this form so that no
    spelling nginx routes to a raw upload location falls through to Django's body-spooling handler."""
    resolved: list[str] = []
    for segment in path.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if resolved:
                resolved.pop()
            continue
        resolved.append(segment)
    last_segment = path.rsplit("/", 1)[-1]
    keeps_trailing_slash = last_segment in ("", ".", "..") and bool(resolved)
    return "/" + "/".join(resolved) + ("/" if keeps_trailing_slash else "")


async def http_dispatcher(scope, receive, send):
    canonical = canonical_path(scope.get("path") or "")
    raw_app = raw_http_apps.get(canonical)
    # OPTIONS stays with Django so corsheaders answers the preflight.
    if raw_app is not None and scope.get("method") != "OPTIONS":
        await raw_app({**scope, "path": canonical}, receive, send)
        return
    await django_asgi_app(scope, receive, send)


# Outermost, so no branch (Django, the raw upload apps, websockets) sees a
# forged underscore spelling of a forwarding header.
application = DropUnderscoreForwardingHeadersMiddleware(
    ProtocolTypeRouter(
        {
            "http": http_dispatcher,
            "websocket": AllowedHostsOriginValidator(
                TicketAuthMiddleware(URLRouter(websocket_urlpatterns))
            ),
        }
    )
)
