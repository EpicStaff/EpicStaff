from django_app.settings import BASE_DIR, env
from tables.services.rbac.first_setup_mode import FirstSetupMode

from src.shared import humanize

DEBUG = env.bool("DJANGO_DEBUG")

SECRET_KEY = env.str("DJANGO_SECRET_KEY")

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")

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
    {"NAME": "tables.services.rbac.utils.printable_ascii_password_validator.PrintableAsciiPasswordValidator"},
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

TUNNEL_URLS_HASH_KEY = "tunnel_urls"

MALLOC_TRIM_INTERVAL = env.time("DJANGO_MALLOC_TRIM_INTERVAL")