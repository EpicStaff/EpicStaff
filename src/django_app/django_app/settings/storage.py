from django_app.settings import env

http = "https" if env.bool("STORAGE_SSL") else "http"
STORAGE_ENDPOINT = f"{http}://{env.str('STORAGE_HOST')}:{env.int('STORAGE_PORT')}"
STORAGE_ACCESS_KEY = env.str("STORAGE_USER")
STORAGE_SECRET_KEY = env.str("STORAGE_PASSWORD")
STORAGE_BUCKET_NAME = env.str("STORAGE_BUCKET")

# TTL for temporary session storage credentials (hours). 0 means no expiration.
# Do not set to 0 in production — credentials will never expire if revocation fails.
STORAGE_TEMP_CREDENTIALS_TTL_HOURS = env.int("STORAGE_TEMP_CREDENTIALS_TTL_HOURS", default=24)
