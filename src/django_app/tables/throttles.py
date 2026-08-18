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


class PasswordResetRequestThrottle(SimpleRateThrottle):
    """
    Throttle for POST /api/auth/password-reset/request/.

    Bucket key is `<ip>|<email-lowercased>` so neither an IP nor an email
    can be used to farm unlimited reset emails. Rate is driven by the
    `password_reset_request` scope (default 5/hour, env var
    `PASSWORD_RESET_REQUEST_THROTTLE_RATE`).

    The endpoint itself returns 200 regardless of whether the email
    exists, so the throttle is the only surface that pushes back on
    automated abuse.
    """

    scope = "password_reset_request"

    def get_cache_key(self, request, view):
        raw = request.data.get("email") or ""
        email = raw.lower().strip() if isinstance(raw, str) else ""
        ip = self.get_ident(request)
        ident = f"{ip}|{email}" if email else ip
        return self.cache_format % {"scope": self.scope, "ident": ident}


class NotifyEmailThrottle(SimpleRateThrottle):
    """
    Throttle for POST /api/notify/email/ (NotifyEmailView, driven by
    notification_tool / channel='email').

    Unlike LoginThrottle/PasswordResetRequestThrottle -- which serve
    anonymous flows and key on `<ip>|<email>` -- this endpoint requires auth,
    so the bucket key is the authenticated caller's user id. That caps how
    many emails a single account (human or a leaked/prompt-injected API key)
    can send regardless of which IP the request comes from, which is the
    relevant abuse vector here: an authenticated agent using this endpoint as
    a mail relay to spam arbitrary external addresses. Rate is driven by the
    `notify_email` scope (default 10/hour, env var
    `NOTIFY_EMAIL_THROTTLE_RATE`).
    """

    scope = "notify_email"

    def get_cache_key(self, request, view):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            ident = str(user.pk)
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}
