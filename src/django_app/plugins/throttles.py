import time

from django.core.cache import cache
from rest_framework.throttling import BaseThrottle, SimpleRateThrottle

from plugins.identity.principals import PluginServiceAccountPrincipal

SERVICE_ACCOUNT_WINDOW_SECONDS = 60
# The counter outlives its minute a little, so a request at the window's edge never meets
# an expired counter between `add` and `incr`.
SERVICE_ACCOUNT_COUNTER_TTL_SECONDS = 70


class PluginTokenIpThrottle(SimpleRateThrottle):
    """Throttle for `POST /api/auth/plugin-token/`, keyed on the client IP (`get_ident`).

    The endpoint is anonymous and cookie-blind, so the IP is the only stable key; each request
    is a guess at a live code, though a code is 43 random characters and lives 60 s. A person's
    pages exchange a code at login and every renewal (about once in 14 minutes per open
    plugin), so 120 a minute leaves room for an office behind one NAT. A fixed rate, not an
    environment variable: nothing about a deployment changes what a browser needs.
    """

    scope = "plugin_token"
    rate = "120/min"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class PluginServiceAccountRateThrottle(BaseThrottle):
    """Caps a plugin service account at its `requests_per_minute`, across every endpoint.

    One of DRF's default throttle classes. Counts only requests made with a service-account
    key; every other caller passes without touching the cache. A fixed one-minute window
    per service account in Django's cache (shared by every worker): over the rate, DRF
    answers 429 `throttled` with `Retry-After` set to the seconds left in the window.
    """

    def __init__(self):
        self._wait_seconds: float | None = None

    def allow_request(self, request, view) -> bool:
        principal = request.user
        if not isinstance(principal, PluginServiceAccountPrincipal):
            return True
        now = time.time()
        window = int(now // SERVICE_ACCOUNT_WINDOW_SECONDS)
        key = f"plugins:sa_rate:{principal.service_account_id}:{window}"
        cache.add(key, 0, timeout=SERVICE_ACCOUNT_COUNTER_TTL_SECONDS)
        if cache.incr(key) <= principal.requests_per_minute:
            return True
        self._wait_seconds = (window + 1) * SERVICE_ACCOUNT_WINDOW_SECONDS - now
        return False

    def wait(self) -> float | None:
        return self._wait_seconds
