from django_app.settings import *

REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
}

# pytest-django forces settings.DEBUG = False for the whole test session
# regardless of what's set above, so SecretCipher's "is DEBUG or is the
# SECRET_KEY explicit" check can't rely on DEBUG here. Set this explicitly
# so the test suite doesn't depend on src/debug.env exporting SECRET_KEY.
SECRET_KEY_IS_EXPLICIT = True
