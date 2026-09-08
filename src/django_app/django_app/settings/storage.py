from django_app.settings import env

http = "https" if env.bool("MINIO_SSL") else "http"
STORAGE_ENDPOINT = f"{http}://{env.str("MINIO_HOST")}:{env.int("MINIO_PORT")}"
STORAGE_ACCESS_KEY = env.str("MINIO_USER")
STORAGE_SECRET_KEY = env.str("MINIO_PASSWORD")
STORAGE_BUCKET_NAME = env.str("MINIO_BUCKET")
