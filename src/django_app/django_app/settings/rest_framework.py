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
    "NUM_PROXIES": 1,
    "DEFAULT_THROTTLE_RATES": {
        "login": env.str("DJANGO_LOGIN_THROTTLE_RATE"),
        "password_reset_request": env.str("DJANGO_PASSWORD_RESET_REQUEST_THROTTLE_RATE"),
        "password_reset_confirm": env.str("DJANGO_PASSWORD_RESET_CONFIRM_THROTTLE_RATE"),
        "token_refresh": env.str("DJANGO_TOKEN_REFRESH_THROTTLE_RATE"),
        "notify_email": env.str("DJANGO_NOTIFY_EMAIL_THROTTLE_RATE"),
    },
}
