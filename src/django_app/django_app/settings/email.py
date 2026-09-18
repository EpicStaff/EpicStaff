from django_app.settings import env


DEFAULT_FROM_EMAIL = env.str("DJANGO_DEFAULT_FROM_EMAIL")
EMAIL_HOST = env.str("DJANGO_EMAIL_HOST")
EMAIL_PORT = env.int("DJANGO_EMAIL_PORT")
EMAIL_HOST_USER = env.str("DJANGO_EMAIL_USER")
EMAIL_HOST_PASSWORD = env.str("DJANGO_EMAIL_PASSWORD")
EMAIL_USE_TLS = env.bool("DJANGO_EMAIL_USE_TLS")
EMAIL_USE_SSL = env.bool("DJANGO_EMAIL_USE_SSL")

# EMAIL_HOST blank -> console backend (reset links printed to stdout) instead
# of a live SMTP relay. mailpit (docker-compose.yaml) is gated behind
# COMPOSE_PROFILES=dev (env.yaml) for exactly this reason — don't hardcode
# EMAIL_BACKEND to SMTP or give DJANGO_EMAIL_HOST's prod default a live
# value; mailpit's web UI is unauthenticated.
if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
