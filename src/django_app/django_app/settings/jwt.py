from datetime import timedelta

from django_app.settings import env
from django_app.settings import SECRET_KEY


JWT_SECRET = env.str("JWT_SECRET", SECRET_KEY)

SIMPLE_JWT = {
    "SIGNING_KEY": JWT_SECRET,
    "ALGORITHM": "HS256",
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", 15)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", 7)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}
