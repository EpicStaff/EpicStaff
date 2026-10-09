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
from tables.graph_collab.ws_auth import TicketAuthMiddleware
from tables.views.storage_upload_stream_view import UPLOAD_STREAM_PATH, upload_stream_app

from django_app.forwarding_headers import DropUnderscoreForwardingHeadersMiddleware
from django_app.routing import websocket_urlpatterns


async def http_dispatcher(scope, receive, send):
    # OPTIONS stays with Django so corsheaders answers the preflight.
    if scope.get("path") == UPLOAD_STREAM_PATH and scope.get("method") != "OPTIONS":
        await upload_stream_app(scope, receive, send)
        return
    await django_asgi_app(scope, receive, send)


# Outermost, so no branch (Django, the upload stream app, websockets) sees a
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
