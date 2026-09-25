from rest_framework.throttling import SimpleRateThrottle


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
