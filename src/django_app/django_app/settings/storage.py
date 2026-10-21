from django_app.settings import env

http = "https" if env.bool("STORAGE_SSL") else "http"
STORAGE_ENDPOINT = f"{http}://{env.str('STORAGE_HOST')}:{env.int('STORAGE_PORT')}"
STORAGE_ACCESS_KEY = env.str("STORAGE_USER")
STORAGE_SECRET_KEY = env.str("STORAGE_PASSWORD")
STORAGE_BUCKET_NAME = env.str("STORAGE_BUCKET")

# TTL for temporary session storage credentials (hours). 0 means no expiration.
# Do not set to 0 in production — credentials will never expire if revocation fails.
STORAGE_TEMP_CREDENTIALS_TTL_HOURS = env.int("STORAGE_TEMP_CREDENTIALS_TTL_HOURS", default=24)

# `default` keeps serving FileFields that still live on local disk (realtime
# recordings). Avatars live in the bucket under `system/`, outside every `org_<id>/`
# prefix, so no organization's scoped credentials can read or overwrite them.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    "avatars": {
        "BACKEND": "rbac.profile.avatar_storage.AvatarStorage",
        "OPTIONS": {
            "bucket_name": STORAGE_BUCKET_NAME,
            "endpoint_url": STORAGE_ENDPOINT,
            "access_key": STORAGE_ACCESS_KEY,
            "secret_key": STORAGE_SECRET_KEY,
            "location": "system",
            "default_acl": None,
            "file_overwrite": True,
            # SigV4 signs with a region; us-east-1 matches what storage-init configures.
            "region_name": "us-east-1",
            "signature_version": "s3v4",
            "addressing_style": "path",
        },
    },
}
