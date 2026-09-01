from django_app.settings import env

STORAGE_ENDPOINT = env.str("STORAGE_ENDPOINT", "")
STORAGE_ACCESS_KEY = env.str("STORAGE_ACCESS_KEY", "")
STORAGE_SECRET_KEY = env.str("STORAGE_SECRET_KEY", "")
STORAGE_BUCKET_NAME = env.str("STORAGE_BUCKET_NAME", "epicstaff")