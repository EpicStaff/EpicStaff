from datetime import timedelta

from src.shared import humanize

from django_app.settings import SECRET_KEY, env

SIMPLE_JWT = {
    "SIGNING_KEY": SECRET_KEY,
    "ALGORITHM": "HS256",
    "ACCESS_TOKEN_LIFETIME": env.get_value(
        "DJANGO_JWT_ACCESS_LIFETIME",
        cast=lambda v: timedelta(seconds=humanize.to_time(v)),
    ),
    "REFRESH_TOKEN_LIFETIME": env.get_value(
        "DJANGO_JWT_REFRESH_LIFETIME",
        cast=lambda v: timedelta(seconds=humanize.to_time(v)),
    ),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    # Binds every token to the user's password hash (claim `hash_password`):
    # a password set invalidates every access and refresh token at once,
    # including rotated refresh tokens that have no OutstandingToken row to
    # blacklist. JWTAuthentication enforces it on access tokens; the refresh
    # endpoint and token introspection enforce it via rbac.identity.tokens.
    "CHECK_REVOKE_TOKEN": True,
}
