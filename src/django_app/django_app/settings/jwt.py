from datetime import timedelta

from django_app.settings import env
from django_app.settings import SECRET_KEY
from src.shared import humanize


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
}
