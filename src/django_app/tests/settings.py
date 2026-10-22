import os

# litellm reads this once, at import: without it every test run fetches the live model
# map from GitHub, and tests asserting real model capabilities change with upstream.
# The Docker images set it too (Dockerfile.dj). Set here because pytest-django imports
# the settings before any conftest or test module can import litellm.
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

from django_app.settings import *  # noqa: E402

REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    # Real JWT/API-key authentication so `auth_client` (Authorization: Bearer
    # <jwt>) actually resolves `request.user` on viewsets that don't declare
    # their own `authentication_classes` (most ModelViewSets in
    # model_view_sets.py). Leaving this at [] silently turns every such
    # request anonymous, so any org-scoped RBAC assertion (HasOrgPermission,
    # IsAuthenticated) built on top of `auth_client` false-403s regardless of
    # the actual permission logic under test.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rbac.identity.authentication.JwtOrApiKeyAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [],
}

# Avatars go to local disk under MEDIA_ROOT, never to the bucket; the URLs are the
# unsigned `/media/<name>` (AvatarStorage's signing is covered by
# storage_tests/test_avatar_storage.py). Set here, not with override_settings: the
# avatar field resolves its storage once, when models load.
STORAGES = {
    **STORAGES,
    "avatars": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
}

# The existing first-setup API tests exercise the browser flow, so the test
# suite runs in `open` mode. Tests for the gate itself opt in explicitly with
# @override_settings(FIRST_SETUP_MODE="cli_only").
FIRST_SETUP_MODE = FirstSetupMode.OPEN
