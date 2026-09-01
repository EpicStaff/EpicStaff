from django_app.settings import BASE_DIR, env
from tables.services.rbac.first_setup_mode import FirstSetupMode

DEBUG = env.bool('DEBUG', False)

SECRET_KEY = env.str('SECRET_KEY')

# host.strip() for host in os.getenv("ALLOWED_HOSTS", "0.0.0.0, 127.0.0.1").split(",")
ALLOWED_HOSTS = ["*"]

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

FRONTEND_BASE_URL = env.str("FRONTEND_BASE_URL").rstrip("/")
FRONTEND_PASSWORD_RESET_PATH = env.str("FRONTEND_PASSWORD_RESET_PATH", "/reset-password")

ROOT_URLCONF = "django_app.urls"
ASGI_APPLICATION = "django_app.asgi.application"

LANGUAGE_CODE = "en-us"
TIME_ZONE = env.str("TIMEZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = env.str("DJANGO_MEDIA_ROOT", BASE_DIR / "media")

FIRST_SETUP_MODE = FirstSetupMode.validate(
    env.str("FIRST_SETUP_MODE", "").strip().lower() or FirstSetupMode.CLI_ONLY
)

DEFAULT_ORGANIZATION_NAME = env.str("DEFAULT_ORGANIZATION_NAME", "") or "Organization"

TELEGRAM_TRIGGER_FIELDS_PATH = BASE_DIR / "tables/utils/data/telegram_fields.json"

GRAPH_WS_TICKET_TTL_SECONDS = 30

PASSWORD_RESET_TOKEN_TTL = env.int("PASSWORD_RESET_TOKEN_TTL", 900)

SSE_TICKET_TTL_SECONDS = 30

PASSWORD_CHANGE_TICKET_TTL_SECONDS = env.int("PASSWORD_CHANGE_TICKET_TTL_SECONDS", 300)

AVATAR_MAX_BYTES = env.int("AVATAR_MAX_BYTES", 5 * 1024 * 1024)  # 10MB
AVATAR_ALLOWED_FORMATS = env.list("AVATAR_ALLOWED_FORMATS", default=["JPEG", "PNG"])
MAX_TOTAL_FILE_SIZE = 10 * 1024 * 1024  # 10MB

TUNNEL_URLS_HASH_KEY = env.str("TUNNEL_URLS_HASH_KEY", "tunnel_urls")
