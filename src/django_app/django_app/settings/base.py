from src.shared import humanize
from tables.services.rbac.first_setup_mode import FirstSetupMode
from tables.validators.upload_settings_validator import (
    parse_minio_duration,
    validate_upload_settings,
)

from django_app.settings import BASE_DIR, env

DEBUG = env.bool("DJANGO_DEBUG")

SECRET_KEY = env.secret("DJANGO_SECRET_KEY")

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "health_check",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "tables",
    "agents",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "django_filters",
    "corsheaders",
    "django_redis",
    "channels",
    "channels_redis",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {
        "NAME": "tables.services.rbac.utils.printable_ascii_password_validator.PrintableAsciiPasswordValidator"
    },
]

FRONTEND_BASE_URL = env.str("DJANGO_FRONTEND_BASE_URL").rstrip("/")
FRONTEND_PASSWORD_RESET_PATH = env.str("DJANGO_FRONTEND_PASSWORD_RESET_PATH")

ROOT_URLCONF = "django_app.urls"
ASGI_APPLICATION = "django_app.asgi.application"

LANGUAGE_CODE = "en-us"
TIME_ZONE = env.str("DJANGO_TIMEZONE")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

FIRST_SETUP_MODE = FirstSetupMode.validate(
    env.str("DJANGO_FIRST_SETUP_MODE", "").strip().lower() or FirstSetupMode.CLI_ONLY
)

DEFAULT_ORGANIZATION_NAME = "Organization"

TELEGRAM_TRIGGER_FIELDS_PATH = BASE_DIR / "tables/utils/data/telegram_fields.json"

GRAPH_WS_TICKET_TTL = 30

SSE_TICKET_TTL = 30

PASSWORD_RESET_TOKEN_TTL = env.time("DJANGO_PASSWORD_RESET_TOKEN_TTL")
PASSWORD_CHANGE_TICKET_TTL = env.time("DJANGO_PASSWORD_CHANGE_TICKET_TTL")

AVATAR_MAX_SIZE = env.byte_size("DJANGO_AVATAR_MAX_SIZE")
AVATAR_ALLOWED_FORMATS = env.list("DJANGO_AVATAR_ALLOWED_FORMATS")
MAX_TOTAL_FILE_SIZE = humanize.to_byte_size("10mb")

MAX_UPLOAD_FILE_SIZE = env.byte_size("DJANGO_MAX_UPLOAD_FILE_SIZE")
MAX_UPLOAD_TOTAL_SIZE = env.byte_size("DJANGO_MAX_UPLOAD_TOTAL_SIZE")

MAX_ARCHIVE_ENTRIES = env.int("DJANGO_MAX_ARCHIVE_ENTRIES")
MAX_ARCHIVE_UNCOMPRESSED_SIZE = env.byte_size("DJANGO_MAX_ARCHIVE_UNCOMPRESSED_SIZE")

ORG_STORAGE_QUOTA = env.byte_size("DJANGO_ORG_STORAGE_QUOTA")
MAX_STREAM_UPLOAD_FILE_SIZE = env.byte_size("DJANGO_MAX_STREAM_UPLOAD_FILE_SIZE")
# Routed to the raw ASGI upload handler in asgi.py, not a URLconf route.
UPLOAD_STREAM_PATH = env.str("DJANGO_UPLOAD_STREAM_PATH")
MAX_ARCHIVE_FILE_SIZE = env.byte_size("DJANGO_MAX_ARCHIVE_FILE_SIZE")
UPLOAD_PART_SIZE = env.byte_size("DJANGO_UPLOAD_PART_SIZE")
UPLOAD_MAX_CONCURRENCY = env.int("DJANGO_UPLOAD_MAX_CONCURRENCY")
UPLOAD_MAX_CONCURRENCY_PER_ORG = env.int("DJANGO_UPLOAD_MAX_CONCURRENCY_PER_ORG")
UPLOAD_SLOT_TIMEOUT = env.time("DJANGO_UPLOAD_SLOT_TIMEOUT")
UPLOAD_IDLE_TIMEOUT = env.time("DJANGO_UPLOAD_IDLE_TIMEOUT")
UPLOAD_MAX_DURATION = env.time("DJANGO_UPLOAD_MAX_DURATION")
ARCHIVE_UPLOAD_CONCURRENCY = env.int("DJANGO_ARCHIVE_UPLOAD_CONCURRENCY")
MINIO_STALE_UPLOADS_EXPIRY = parse_minio_duration(
    "MINIO_STALE_UPLOADS_EXPIRY", env.str("MINIO_STALE_UPLOADS_EXPIRY")
)
validate_upload_settings(
    part_size=UPLOAD_PART_SIZE,
    storage_quota=ORG_STORAGE_QUOTA,
    max_stream_file_size=MAX_STREAM_UPLOAD_FILE_SIZE,
    max_archive_file_size=MAX_ARCHIVE_FILE_SIZE,
    max_concurrency=UPLOAD_MAX_CONCURRENCY,
    per_org_limit=UPLOAD_MAX_CONCURRENCY_PER_ORG,
    slot_timeout=UPLOAD_SLOT_TIMEOUT,
    idle_timeout=UPLOAD_IDLE_TIMEOUT,
    max_duration=UPLOAD_MAX_DURATION,
    stale_uploads_expiry=MINIO_STALE_UPLOADS_EXPIRY,
)

TUNNEL_URLS_HASH_KEY = "tunnel_urls"

MALLOC_TRIM_INTERVAL = env.time("DJANGO_MALLOC_TRIM_INTERVAL")

# Controls whether SoftDeleteMixin.delete() soft-deletes (mark inactive) or hard-deletes.
SOFT_DELETE = env.bool("DJANGO_SOFT_DELETE", False)

REFRESH_COOKIE_SECURE = env.bool("DJANGO_REFRESH_COOKIE_SECURE")

DJANGO_API_KEY = env.str("DJANGO_API_KEY")
