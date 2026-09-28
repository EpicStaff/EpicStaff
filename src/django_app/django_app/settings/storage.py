from django_app.settings import env

http = "https" if env.bool("STORAGE_SSL") else "http"
STORAGE_ENDPOINT = f"{http}://{env.str('STORAGE_HOST')}:{env.int('STORAGE_PORT')}"
STORAGE_ACCESS_KEY = env.str("STORAGE_USER")
STORAGE_SECRET_KEY = env.str("STORAGE_PASSWORD")
STORAGE_BUCKET_NAME = env.str("STORAGE_BUCKET")
