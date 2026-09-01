from corsheaders.defaults import default_headers

from django_app.settings import env

CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS")

CORS_ALLOW_HEADERS = (
    *default_headers,
    "dnt",
    "origin",
    "accept-encoding",
    "x-twilio-account-sid",
    "x-twilio-auth-token",
    "x-organization-id",
)