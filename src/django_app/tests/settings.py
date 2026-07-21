from django_app.settings import *

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
        "tables.services.rbac.authentication.JwtOrApiKeyAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [],
}
