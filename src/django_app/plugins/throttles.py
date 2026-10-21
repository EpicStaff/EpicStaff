from rest_framework.throttling import SimpleRateThrottle


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
