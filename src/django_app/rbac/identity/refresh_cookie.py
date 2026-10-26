"""The HttpOnly cookie that carries the refresh token, and the only code that reads or writes it.

Over HTTPS (`settings.REFRESH_COOKIE_SECURE`) the cookie is `__Host-auth.refresh` on `Path=/`:
the `__Host-` prefix makes browsers refuse it unless it is `Secure`, has no `Domain` and has
`Path=/`, so a sibling host (a plugin page) cannot set one that EpicStaff's host would receive.
Over plain http no prefix is possible, and the cookie keeps its old name and path.

The cookie is read from the raw `Cookie` header, never from `request.COOKIES`: Django keeps the
last of several cookies with one name, so a planted duplicate would decide which session is used.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.http.cookie import parse_cookie
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

REMEMBER_ME_CLAIM = "remember_me"

# The only cookie over plain http, and the one an HTTPS deployment used before the prefix.
_LEGACY_COOKIE_NAME = "auth.refresh"
_LEGACY_COOKIE_PATH = "/api/auth/"
_HOST_PREFIXED_COOKIE_NAME = "__Host-auth.refresh"
_HOST_PREFIXED_COOKIE_PATH = "/"

# Cap for non-remembered sessions. Applied to both the cookie Max-Age and
# the JWT `exp` so browser session-restore cannot revive an old session.
NON_REMEMBER_REFRESH_LIFETIME = timedelta(minutes=30)


def refresh_cookie_name() -> str:
    """Return the refresh cookie's name: `__Host-auth.refresh` over HTTPS, else `auth.refresh`."""
    return _HOST_PREFIXED_COOKIE_NAME if settings.REFRESH_COOKIE_SECURE else _LEGACY_COOKIE_NAME


def refresh_cookie_path() -> str:
    """Return the refresh cookie's path: `/` over HTTPS (the prefix demands it), else `/api/auth/`."""
    return _HOST_PREFIXED_COOKIE_PATH if settings.REFRESH_COOKIE_SECURE else _LEGACY_COOKIE_PATH


def set_refresh_cookie(response: Response, refresh_token: str, *, remember_me: bool) -> Response:
    """Embed the ``remember_me`` claim and write the refresh cookie.

    ``remember_me=True``  -> Max-Age = ``REFRESH_TOKEN_LIFETIME``.
    ``remember_me=False`` -> Max-Age and JWT ``exp`` = 30 minutes.

    Over HTTPS the cookie of the old name is expired in the same response, so it does not
    linger in the browser until its own expiry after the switch to the prefixed name.

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

    _write_cookie(response, refresh_cookie_name(), str(token), max_age, refresh_cookie_path())
    _expire_legacy_cookie_over_https(response)
    return response


def read_remember_me_claim(refresh_token: str | None) -> bool:
    """Return the ``remember_me`` claim from an incoming refresh token,
    or ``False`` if missing/unreadable. Does not authenticate the token —
    pair with ``PasswordBoundTokenRefreshSerializer`` for the 401.
    """
    if not refresh_token:
        return False
    try:
        return bool(RefreshToken(refresh_token).payload.get(REMEMBER_ME_CLAIM, False))
    except TokenError:
        return False


def clear_refresh_cookie(response: Response) -> Response:
    """Expire the refresh cookie and, over HTTPS, the cookie of the old name too."""
    _write_cookie(response, refresh_cookie_name(), "", 0, refresh_cookie_path())
    _expire_legacy_cookie_over_https(response)
    return response


def get_refresh_from_cookie(request) -> str | None:
    """Return the refresh token the request carries, or None.

    The `Cookie` header is split into its `;`-separated chunks and each is parsed as Django's
    `parse_cookie` does (a chunk without `=` has the empty name). The value counts only when
    the current cookie name appears exactly once with a non-empty value: a second cookie of the
    same name (a copy planted from a sibling host, or a nameless cookie whose value looks like
    `__Host-auth.refresh=...`) leaves the request without a session rather than choosing one.
    Over HTTPS the old name is never read.
    """
    name = refresh_cookie_name()
    values = [
        value
        for chunk in request.META.get("HTTP_COOKIE", "").split(";")
        for chunk_name, value in parse_cookie(chunk).items()
        if chunk_name == name
    ]
    if len(values) != 1 or not values[0]:
        return None
    return values[0]


def _write_cookie(response: Response, name: str, value: str, max_age: int, path: str) -> None:
    response.set_cookie(
        key=name,
        value=value,
        max_age=max_age,
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite="Lax",
        path=path,
    )


def _expire_legacy_cookie_over_https(response: Response) -> None:
    if settings.REFRESH_COOKIE_SECURE:
        _write_cookie(response, _LEGACY_COOKIE_NAME, "", 0, _LEGACY_COOKIE_PATH)
