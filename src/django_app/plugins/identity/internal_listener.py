"""Whether a request came through nginx's internal listener on the plugins network.

Plugin credentials (a service-account key, a node key) are accepted only there: the listener
sets `X-Plugin-Network-Secret` to `PLUGINS_GATEWAY_SECRET`, a value no client ever learns, so
a key that leaks is useless from anywhere but the plugins network.
"""

import hmac

from django.conf import settings

UNCONFIGURED_SECRET = "none"
NETWORK_SECRET_META_KEY = "HTTP_X_PLUGIN_NETWORK_SECRET"


def holds_gateway_secret(presented: str) -> bool:
    """Whether `presented` is the configured gateway secret; never while none is configured."""
    configured = settings.PLUGINS_GATEWAY_SECRET or ""
    if configured in ("", UNCONFIGURED_SECRET):
        return False
    return hmac.compare_digest(presented.encode("utf-8"), configured.encode("utf-8"))


def came_through_internal_listener(request) -> bool:
    return holds_gateway_secret(request.META.get(NETWORK_SECRET_META_KEY, ""))
