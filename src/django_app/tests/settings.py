import os

# django_app.settings refuses to import without these; set them before the star-import
# below so the suite does not silently depend on src/debug.env being present.
os.environ.setdefault("SECRET_KEY", "test-only-secret-key-not-used-outside-pytest")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret-not-used-outside-pytest")

from django_app.settings import *  # noqa: E402,F403

REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
}
