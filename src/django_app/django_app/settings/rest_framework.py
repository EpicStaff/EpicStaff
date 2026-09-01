from django_app.settings import env

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
    ],
    "EXCEPTION_HANDLER": "utils.exception_handler.custom_exception_handler",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "tables.services.rbac.authentication.JwtAuthentication",
        "tables.services.rbac.authentication.ApiKeyAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # One reverse proxy (nginx) sits in front of Django. Without this, DRF
    # keys throttles on the whole X-Forwarded-For chain, whose left-hand side
    # the client controls - so any throttle could be bypassed by varying the
    # header. With 1, only the entry nginx itself appended is used.
    "NUM_PROXIES": 1,
    "DEFAULT_THROTTLE_RATES": {
        "login": env.str("LOGIN_THROTTLE_RATE", "5/min"),
        "password_reset_request": env.str("PASSWORD_RESET_REQUEST_THROTTLE_RATE", "5/hour"),
        "password_reset_confirm": env.str("PASSWORD_RESET_CONFIRM_THROTTLE_RATE", "10/hour"),
        "token_refresh": env.str("TOKEN_REFRESH_THROTTLE_RATE", "30/min"),
        "notify_email": env.str("NOTIFY_EMAIL_THROTTLE_RATE", "10/hour"),
    },
}
