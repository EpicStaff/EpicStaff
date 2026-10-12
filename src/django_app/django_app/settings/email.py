from django_app.settings import env

DEFAULT_FROM_EMAIL = env.str("DJANGO_DEFAULT_FROM_EMAIL")
EMAIL_HOST = env.str("DJANGO_EMAIL_HOST")
EMAIL_PORT = env.int("DJANGO_EMAIL_PORT")
EMAIL_HOST_USER = env.str("DJANGO_EMAIL_USER")
EMAIL_HOST_PASSWORD = env.str("DJANGO_EMAIL_PASSWORD")
EMAIL_USE_TLS = env.bool("DJANGO_EMAIL_USE_TLS")
EMAIL_USE_SSL = env.bool("DJANGO_EMAIL_USE_SSL")
# Seconds the SMTP backend waits on the relay's socket. Django's default is
# no timeout: a relay that accepts the connection and never answers would hang
# the password-reset worker threads for good, fill their backlog and stop
# every reset email until the process restarts. A healthy relay answers well
# within this, TLS handshake included.
EMAIL_TIMEOUT = 10

# EMAIL_HOST blank -> console backend instead of a live SMTP relay. The console
# backend writes every message to the application log, so nothing secret may go
# through it: password-reset links are not sent without SMTP (gated by
# `SmtpConfigService`), and operators reset passwords with
# `manage.py reset_password` instead.
# mailpit (docker-compose.yaml) is gated behind COMPOSE_PROFILES=dev (env.yaml)
# so that prod never relays through it by accident — don't hardcode
# EMAIL_BACKEND to SMTP or give DJANGO_EMAIL_HOST's prod default a live value;
# mailpit's web UI is unauthenticated.
if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
