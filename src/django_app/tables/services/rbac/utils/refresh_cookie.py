from __future__ import annotations

from django.conf import settings
from rest_framework.response import Response

REFRESH_COOKIE_NAME = "auth.refresh"
REFRESH_COOKIE_PATH = "/api/auth/"


def set_refresh_cookie(
    response: Response, refresh_token: str, *, persistent: bool = True
) -> Response:
    """Set the refresh-token cookie.

    persistent=True  -> Max-Age is the configured REFRESH_TOKEN_LIFETIME
                        (cookie survives browser restart).
    persistent=False -> no Max-Age / Expires => browser session cookie,
                        dropped when the browser session ends.
    """
    max_age = (
        int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds())
        if persistent
        else None
    )
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=max_age,
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite="Lax",
        path=REFRESH_COOKIE_PATH,
    )
    return response


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
