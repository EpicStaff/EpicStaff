from django_app.settings import env

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "tables.User"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "USER": env.str("DJANGO_DB_USER"),
        "PASSWORD": env.str("DJANGO_DB_PASSWORD"),
        "HOST": env.str("DB_HOST"),
        "PORT": env.int("DB_PORT"),
        "NAME": env.str("DB_NAME"),
    }
}
