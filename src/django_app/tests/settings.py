from django_app.settings import *

REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
}

# The existing first-setup API tests exercise the browser flow, so the test
# suite runs in `open` mode. Tests for the gate itself opt in explicitly with
# @override_settings(FIRST_SETUP_MODE="cli_only").
FIRST_SETUP_MODE = FirstSetupMode.OPEN
