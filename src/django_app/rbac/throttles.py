from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle


class LoginThrottle(SimpleRateThrottle):
    """
    Throttle for credential-accepting endpoints (LoginView, SwaggerTokenView,
    PasswordChangeRequestView).

    Bucket key is the composite `<ip>|<email>`, so one account can't be
    guessed at from one IP past the configured rate, and a user locked out by
    their own typos doesn't lock out everyone else behind the same NAT. Rate
    is driven by the `login` scope (default 5/min, env var
    `DJANGO_LOGIN_THROTTLE_RATE`).

    It does not limit an IP that rotates emails (password spraying): every new
    email is a fresh bucket. `LoginIpThrottle` covers that, and both login
    views apply both. `PasswordChangeRequestView`'s body has no email, so
    there the key is the IP alone.
    """

    scope = "login"

    def get_cache_key(self, request, view):
        raw = request.data.get("email") or request.data.get("username") or ""
        email = raw.lower().strip() if isinstance(raw, str) else ""
        ip = self.get_ident(request)
        ident = f"{ip}|{email}" if email else ip
        return self.cache_format % {"scope": self.scope, "ident": ident}


class LoginIpThrottle(AnonRateThrottle):
    """
    IP-only throttle for LoginView and SwaggerTokenView, applied alongside
    `LoginThrottle`.

    `LoginThrottle` keys on `<ip>|<email>`, so an IP trying one common
    password against many accounts gets a fresh allowance per account and is
    never stopped; there is no account lockout behind it either. Keyed on IP
    alone, this caps the total number of guesses one address can make,
    whatever emails it names. Its 429 depends only on the caller's IP, so it
    says nothing about which accounts exist. Neither view authenticates
    (`SwaggerTokenView` sets `authentication_classes = []`, `LoginView`
    inherits `()` from simplejwt's `TokenViewBase`), so every caller is
    anonymous and `AnonRateThrottle` always applies.

    Rate is driven by the `login_ip` scope (default 20/min, env var
    `DJANGO_LOGIN_IP_THROTTLE_RATE`). A person logs in a few times a day,
    since the refresh cookie keeps the session alive, so 20/min leaves an
    office behind one NAT room for a morning burst of logins and the odd
    mistyped password, while a single IP is held to four accounts' worth of
    the per-account budget per minute instead of an unbounded number. It also
    bounds the password-hashing work one IP can make the server do.
    """

    scope = "login_ip"


class PasswordResetRequestThrottle(SimpleRateThrottle):
    """
    Throttle for POST /api/auth/password-reset/request/.

    Bucket key is `<ip>|<email-lowercased>`, so one mailbox cannot be
    flooded with reset emails from one IP. Rate is driven by the
    `password_reset_request` scope (default 5/hour, env var
    `DJANGO_PASSWORD_RESET_REQUEST_THROTTLE_RATE`).

    It does not limit an IP that rotates emails: every new email is a fresh
    bucket. `PasswordResetRequestIpThrottle` covers that, and the view
    applies both.
    """

    scope = "password_reset_request"

    def get_cache_key(self, request, view):
        raw = request.data.get("email") or ""
        email = raw.lower().strip() if isinstance(raw, str) else ""
        ip = self.get_ident(request)
        ident = f"{ip}|{email}" if email else ip
        return self.cache_format % {"scope": self.scope, "ident": ident}


class PasswordResetRequestIpThrottle(AnonRateThrottle):
    """
    IP-only throttle for POST /api/auth/password-reset/request/, applied
    alongside `PasswordResetRequestThrottle`.

    Each request queues a background job, and a handful of worker threads
    per process drain them far slower than the endpoint accepts requests.
    An IP rotating random emails would never hit the `ip|email` bucket, but
    would keep the job backlog full, and every legitimate reset would then be
    dropped behind the same "link has been sent" answer. Keyed on IP alone,
    like `PasswordResetConfirmThrottle`; its 429 depends only on the caller's
    IP, so it says nothing about which accounts exist.

    Rate is driven by the `password_reset_request_ip` scope (default 20/hour,
    env var `DJANGO_PASSWORD_RESET_REQUEST_IP_THROTTLE_RATE`). A person needs one or
    two requests; 20 leaves room for several users behind one NAT, while one
    IP can no longer queue jobs faster than two workers clear them.
    """

    scope = "password_reset_request_ip"


class TokenRefreshThrottle(AnonRateThrottle):
    """
    Throttle for POST /api/auth/refresh/.

    Keyed on IP alone. Unlike the throttles above there is nothing to compose
    the IP with: the refresh token arrives in an HttpOnly cookie, so the
    request carries no caller-supplied identifier at all. `AnonRateThrottle`
    already keys on `get_ident(request)`, so no custom `get_cache_key` is
    needed -- and because the view sets `authentication_classes = []`, every
    caller is anonymous and the throttle always applies.

    Rate is driven by the `token_refresh` scope (default 30/min, env var
    `DJANGO_TOKEN_REFRESH_THROTTLE_RATE`). Deliberately generous: a browser refreshes
    about once per `ACCESS_TOKEN_LIFETIME` (15 min by default), so this only
    bites on automated replay of a stolen or guessed refresh cookie.
    """

    scope = "token_refresh"


class PasswordResetConfirmThrottle(AnonRateThrottle):
    """
    Throttle for POST /api/auth/password-reset/confirm/.

    Keyed on IP alone, and deliberately NOT on the submitted token: the token
    is the very thing an attacker varies, so keying on it would hand out a
    fresh bucket per guess and throttle nothing. IP is the only stable
    dimension on this request.

    Rate is driven by the `password_reset_confirm` scope (default 10/hour, env
    var `DJANGO_PASSWORD_RESET_CONFIRM_THROTTLE_RATE`). Tight because a legitimate
    user confirms once per reset email, while the endpoint is anonymous and
    each call is a guess at a live token.
    """

    scope = "password_reset_confirm"
