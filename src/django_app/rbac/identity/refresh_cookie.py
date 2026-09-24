from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

REFRESH_COOKIE_NAME = "auth.refresh"
REFRESH_COOKIE_PATH = "/api/auth/"
REMEMBER_ME_CLAIM = "remember_me"

# Cap for non-remembered sessions. Applied to both the cookie Max-Age and
# the JWT `exp` so browser session-restore cannot revive an old session.
NON_REMEMBER_REFRESH_LIFETIME = timedelta(minutes=30)


def set_refresh_cookie(response: Response, refresh_token: str, *, remember_me: bool) -> Response:
    """Embed the ``remember_me`` claim and write the refresh cookie.

    ``remember_me=True``  -> Max-Age = ``REFRESH_TOKEN_LIFETIME``.
    ``remember_me=False`` -> Max-Age and JWT ``exp`` = 30 minutes.

    Assumes ``refresh_token`` was just minted by this process; a decode
    failure is a server bug and is left to propagate.
    """
    token = RefreshToken(refresh_token)
    token[REMEMBER_ME_CLAIM] = remember_me
    if remember_me:
        max_age = int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds())
    else:
        token.set_exp(lifetime=NON_REMEMBER_REFRESH_LIFETIME)
        max_age = int(NON_REMEMBER_REFRESH_LIFETIME.total_seconds())

    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=str(token),
        max_age=max_age,
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite="Lax",
        path=REFRESH_COOKIE_PATH,
    )
    return response


def read_remember_me_claim(refresh_token: str | None) -> bool:
    """Return the ``remember_me`` claim from an incoming refresh token,
    or ``False`` if missing/unreadable. Does not authenticate the token —
    pair with ``TokenRefreshSerializer`` for the 401.
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
