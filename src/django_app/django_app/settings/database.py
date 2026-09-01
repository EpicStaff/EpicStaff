from django_app.settings import env

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "tables.User"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env.str("DB_NAME", "crew"),
        "USER": env.str("DB_USER", "postgres"),
        "PASSWORD": env.str("POSTGRES_PASSWORD", "admin"),
        "HOST": env.str("DB_HOST_NAME", "localhost"),
        "PORT": env.int("DB_PORT", 5432),
    }
}
