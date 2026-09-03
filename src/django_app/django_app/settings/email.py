from django_app.settings import env


DEFAULT_FROM_EMAIL = env.str("DJANGO_DEFAULT_FROM_EMAIL")
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env.str("DJANGO_EMAIL_HOST")
EMAIL_PORT = env.int("DJANGO_EMAIL_PORT")
EMAIL_HOST_USER = env.str("DJANGO_EMAIL_USER")
EMAIL_HOST_PASSWORD = env.str("DJANGO_EMAIL_PASSWORD")
EMAIL_USE_TLS = env.bool("DJANGO_EMAIL_USE_TLS")
EMAIL_USE_SSL = env.bool("DJANGO_EMAIL_USE_SSL")
