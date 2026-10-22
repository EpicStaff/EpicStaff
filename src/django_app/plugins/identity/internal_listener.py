"""Which of nginx's two plugin listeners a request came through, if either.

Plugin credentials (a service-account key, a node key) are accepted only through a listener:
both set `X-Plugin-Network-Secret` to `PLUGINS_GATEWAY_SECRET`, a value no client ever learns,
so a key that leaks is useless from anywhere else.

- The internal listener (8081) serves the plugins network: the plugin node and the plugin
  backends it runs. Node keys and node-purpose service-account keys work only there.
- The development API listener (8082) exists only in plugin development mode and is
  published only on the host's loopback. It also sets `X-Plugin-Development-Listener: 1`, and
  development-purpose keys work only through it.

Both listeners send Django only the headers they set themselves (`proxy_pass_request_headers
off`), and every other server blanks both headers, so no client can send either.
"""

import hmac

from django.conf import settings

UNCONFIGURED_SECRET = "none"
NETWORK_SECRET_META_KEY = "HTTP_X_PLUGIN_NETWORK_SECRET"
DEVELOPMENT_LISTENER_HEADER = "X-Plugin-Development-Listener"
DEVELOPMENT_LISTENER_VALUE = "1"
DEVELOPMENT_LISTENER_META_KEY = "HTTP_X_PLUGIN_DEVELOPMENT_LISTENER"


def holds_gateway_secret(presented: str) -> bool:
    """Whether `presented` is the configured gateway secret; never while none is configured."""
    configured = settings.PLUGINS_GATEWAY_SECRET or ""
    if configured in ("", UNCONFIGURED_SECRET):
        return False
    return hmac.compare_digest(presented.encode("utf-8"), configured.encode("utf-8"))


def came_through_internal_listener(request) -> bool:
    """Whether the request came through one of the two listeners (it holds the network secret)."""
    return holds_gateway_secret(request.META.get(NETWORK_SECRET_META_KEY, ""))


def came_through_development_listener(request) -> bool:
    """Whether a request that holds the network secret came through the development listener."""
    return request.META.get(DEVELOPMENT_LISTENER_META_KEY) == DEVELOPMENT_LISTENER_VALUE


def names_development_listener(request) -> bool:
    """Whether the request carries the development listener's header at all, with any value.

    Node credentials are refused on any such request, so a value other than the listener's
    own never lets one through.
    """
    return DEVELOPMENT_LISTENER_META_KEY in request.META
