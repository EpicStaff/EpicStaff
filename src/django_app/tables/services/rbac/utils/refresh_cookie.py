from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

REFRESH_COOKIE_NAME = "auth.refresh"
REFRESH_COOKIE_PATH = "/api/auth/"
REMEMBER_ME_CLAIM = "remember_me"

# Ceiling on how long a *non-remembered* refresh session may live, in either
# the cookie ``Max-Age`` or the JWT ``exp`` claim. Chosen so that:
#   * browsers that restore session cookies on relaunch (Chrome's "Continue
#     where you left off") cannot revive an old session indefinitely — the
#     cookie is a real ``Max-Age`` cookie now, not a session cookie;
#   * the server-side token authority matches the cookie, so a leaked cookie
#     cannot outlive its Max-Age even if replayed out-of-band.
NON_REMEMBER_REFRESH_LIFETIME = timedelta(minutes=30)


def set_refresh_cookie(
    response: Response, refresh_token: str, *, remember_me: bool
) -> Response:
    """Embed the ``remember_me`` claim on the refresh token and attach it to
    ``response`` as the HttpOnly refresh cookie.

    Every view that issues a refresh token goes through this helper so the
    persistence intent survives rotation without any client-visible state,
    and the cookie's ``Max-Age`` always matches the claim.

    ``remember_me=True``  -> ``Max-Age`` is the configured
        ``REFRESH_TOKEN_LIFETIME`` (cookie survives browser restart).
    ``remember_me=False`` -> ``Max-Age`` and the JWT ``exp`` are both capped
        at :data:`NON_REMEMBER_REFRESH_LIFETIME` (30 minutes) so an
        unremembered session cannot be revived by browser session-restore
        features and cannot be replayed past its cookie lifetime.

    ``refresh_token`` is expected to be one this process just minted (via
    ``TokenObtainPairSerializer`` / ``TokenRefreshSerializer`` /
    ``TokenPair.for_user``). Failing to decode it here indicates a
    server-side bug (mismatched ``JWT_SECRET``, clock skew, tampered
    settings) and is intentionally allowed to propagate as a 500 rather
    than silently issuing a cookie without the claim.
    """
    token = RefreshToken(refresh_token)
    token[REMEMBER_ME_CLAIM] = remember_me
    if remember_me:
        max_age = int(
            settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()
        )
    else:
        # Shrink the JWT's own expiry to match the cookie so the server
        # rejects the token past the 30-minute window even if the cookie
        # somehow leaks past its Max-Age.
        token.set_exp(lifetime=NON_REMEMBER_REFRESH_LIFETIME)
        max_age = int(NON_REMEMBER_REFRESH_LIFETIME.total_seconds())
    encoded = str(token)

    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=encoded,
        max_age=max_age,
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite="Lax",
        path=REFRESH_COOKIE_PATH,
    )
    return response


def read_remember_me_claim(refresh_token: str | None) -> bool:
    """Return the ``remember_me`` claim from an *incoming* refresh token,
    or ``False`` when the token is missing or cannot be decoded.

    Intended for callers that need the persistence intent *before* rotation
    (e.g. ``CookieTokenRefreshView``, ``PasswordChangeConfirmView``). This
    helper does **not** authenticate the token — pair it with a proper
    validation step (``TokenRefreshSerializer`` or equivalent) which will
    surface the correct ``401`` when the token is bad.

    The ``False`` fallback is deliberate and safe: on an unreadable token
    the caller either returns ``401`` (and the claim value is discarded)
    or issues a short-lived cookie on the rotated token, which is the
    least-privileged default.
    """
    if not refresh_token:
        return False
    try:
        return bool(RefreshToken(refresh_token).payload.get(REMEMBER_ME_CLAIM, False))
    except TokenError:
        return False


def clear_refresh_cookie(response: Response) -> Response:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value="",
        max_age=0,
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite="Lax",
        path=REFRESH_COOKIE_PATH,
    )
    return response


def get_refresh_from_cookie(request) -> str | None:
    return request.COOKIES.get(REFRESH_COOKIE_NAME)
