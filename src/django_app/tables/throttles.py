from rest_framework.throttling import SimpleRateThrottle


class LoginThrottle(SimpleRateThrottle):
    """
    Throttle for credential-accepting endpoints (LoginView, SwaggerTokenView).

    Bucket key is the composite `<ip>|<email>` so a single IP can't exhaust
    every user's quota and a single email can't be attacked from one IP past
    the configured rate. Rate is driven by the `login` scope in DRF settings,
    which in turn reads the `LOGIN_THROTTLE_RATE` env var (default 5/min).
    """

    scope = "login"

    def get_cache_key(self, request, view):
        raw = request.data.get("email") or request.data.get("username") or ""
        email = raw.lower().strip() if isinstance(raw, str) else ""
        ip = self.get_ident(request)
        ident = f"{ip}|{email}" if email else ip
        return self.cache_format % {"scope": self.scope, "ident": ident}
