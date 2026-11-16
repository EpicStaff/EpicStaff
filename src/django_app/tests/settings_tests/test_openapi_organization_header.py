"""The OpenAPI schema lists the `X-Organization-Id` header exactly where a user session needs it.

The header (security scheme `OrganizationId`) names the active organization of a user
session. It is documented only together with `BearerAuth`, in the same security
requirement (both must be sent), and only on operations whose view acts in the active
organization. It never stands alone as a way to authenticate, never accompanies an API
key or a plugin key (they act in their own organization), and never appears on anonymous
operations or on views that declare `uses_organization_context = False`.

A view may only declare that opt-out when it truly never reads the active organization,
so an opted-out view must not be gated by `HasOrgPermission` or scope its queryset
through `OrgScopedResolverMixin`. The check reads the declared `permission_classes`;
a `get_permissions()` override is not seen.
"""

from importlib import import_module, reload

import pytest
from django.conf import settings
from django.test import override_settings
from django.urls import URLResolver, clear_url_caches, get_resolver
from django.utils.module_loading import import_string
from drf_spectacular.generators import SchemaGenerator
from rest_framework.views import APIView

from django_app.settings.rest_framework import REST_FRAMEWORK as PRODUCTION_REST_FRAMEWORK
from rbac.access.gates import HasOrgPermission
from rbac.scoping.mixins import OrgScopedResolverMixin
from tables.views.storage_upload_stream_view import UPLOAD_STREAM_PATH

ORG_HEADER = "OrganizationId"
KEY_SCHEMES = ("ApiKeyAuth", "PluginKeyAuth")
HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


def _reload_root_urlconf():
    clear_url_caches()
    reload(import_module(settings.ROOT_URLCONF))
    clear_url_caches()


@pytest.fixture(scope="module", autouse=True)
def plugin_routes_mounted():
    """Mount the plugin routes, whatever the environment's PLUGINS_ENABLED says."""
    with override_settings(PLUGINS_ENABLED=True):
        _reload_root_urlconf()
        yield
    _reload_root_urlconf()


@pytest.fixture(scope="module")
def production_authentication():
    """Give views that rely on the default authentication the production classes.

    tests/settings.py swaps the default for `JwtOrApiKeyAuthentication`, which has no
    OpenAPI extension, so those views would document no BearerAuth at all. APIView reads
    the default once, at import, hence the class attribute is patched.
    """
    classes = [
        import_string(path) for path in PRODUCTION_REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]
    ]
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(APIView, "authentication_classes", classes)
        yield


@pytest.fixture(scope="module")
def schema(plugin_routes_mounted, production_authentication):
    return SchemaGenerator().get_schema(request=None, public=True)


@pytest.fixture(scope="module")
def operations(schema):
    return [
        (method.upper(), path, operation.get("security") or [])
        for path, path_item in schema["paths"].items()
        for method, operation in path_item.items()
        if method in HTTP_METHODS
    ]


def test_organization_scheme_is_the_integer_org_id_header(schema):
    scheme = schema["components"]["securitySchemes"][ORG_HEADER]

    assert (scheme["type"], scheme["in"], scheme["name"]) == (
        "apiKey",
        "header",
        "X-Organization-Id",
    )
    assert "integer" in scheme["description"].lower()
    assert "uuid" not in scheme["description"].lower()


def test_every_referenced_security_scheme_is_defined(schema, operations):
    defined = set(schema["components"]["securitySchemes"])

    undefined = {
        name for _, _, security in operations for requirement in security for name in requirement
    } - defined

    assert undefined == set()


def test_organization_header_never_authenticates_alone_only_joins_a_user_session(operations):
    offenders = [
        (method, path, requirement)
        for method, path, security in operations
        for requirement in security
        if ORG_HEADER in requirement and "BearerAuth" not in requirement
    ]

    assert offenders == []


def test_organization_header_never_accompanies_an_api_key_or_plugin_key(operations):
    offenders = [
        (method, path, requirement)
        for method, path, security in operations
        for requirement in security
        if ORG_HEADER in requirement and any(scheme in requirement for scheme in KEY_SCHEMES)
    ]

    assert offenders == []


def test_optional_auth_operations_do_not_list_the_organization_header(operations):
    optional_auth = [
        (method, path, security) for method, path, security in operations if {} in security
    ]

    offenders = [
        (method, path)
        for method, path, security in optional_auth
        if any(ORG_HEADER in requirement for requirement in security)
    ]

    assert optional_auth, "expected optional-auth operations such as /api/auth/refresh/"
    assert offenders == []


@pytest.mark.parametrize(
    ("path", "method", "header_expected"),
    [
        # The org-scoped views, including one documented by a postprocessing hook.
        ("/api/permissions/me/", "get", True),
        ("/api/graphs/", "get", True),
        (UPLOAD_STREAM_PATH, "post", True),
        ("/api/realtime-channels/", "get", True),
        ("/api/plugins/available/", "get", True),
        # Cross-org and per-user views: no request depends on the active org.
        ("/api/permissions/me/orgs/", "get", False),
        ("/api/permissions/catalog/", "get", False),
        ("/api/admin/roles/", "get", False),
        ("/api/admin/memberships/", "get", False),
        ("/api/admin/users/", "get", False),
        ("/api/admin/plugins/", "get", False),
        ("/api/profile/api-keys/", "get", False),
        # Opted out on the view class.
        ("/api/run-session/", "post", False),
        # Opted out on one action of an org-scoped viewset; its siblings keep the header.
        ("/api/realtime-channels/lookup-by-token/", "get", False),
    ],
)
def test_organization_header_is_listed_only_on_org_context_operations(
    schema, path, method, header_expected
):
    security = schema["paths"][path][method]["security"]

    requirements_with_header = [
        sorted(requirement) for requirement in security if ORG_HEADER in requirement
    ]

    expected = [["BearerAuth", ORG_HEADER]] if header_expected else []
    assert requirements_with_header == expected


def _drf_callbacks(patterns, prefix=""):
    for pattern in patterns:
        route = prefix + str(pattern.pattern)
        if isinstance(pattern, URLResolver):
            yield from _drf_callbacks(pattern.url_patterns, route)
        elif hasattr(pattern.callback, "cls"):
            yield route, pattern.callback


def test_views_opting_out_of_organization_context_do_not_read_the_active_org(
    plugin_routes_mounted,
):
    class_level_opt_outs = []
    action_level_opt_outs = []
    gated_by_org_permission = []
    scoped_by_org_mixin = []

    for route, callback in _drf_callbacks(get_resolver().url_patterns):
        view_class = callback.cls
        # A router passes `@action` kwargs as initkwargs; they override the class attribute.
        initkwargs = getattr(callback, "initkwargs", None) or {}
        class_value = getattr(view_class, "uses_organization_context", True)
        if initkwargs.get("uses_organization_context", class_value):
            continue

        if class_value is False:
            class_level_opt_outs.append(route)
            if issubclass(view_class, OrgScopedResolverMixin):
                scoped_by_org_mixin.append((route, view_class.__name__))
        else:
            action_level_opt_outs.append(route)

        permission_classes = initkwargs.get("permission_classes", view_class.permission_classes)
        # A composed permission (`A & B`) is an instance, not a class; skip it rather than crash.
        if any(
            isinstance(permission, type) and issubclass(permission, HasOrgPermission)
            for permission in permission_classes
        ):
            gated_by_org_permission.append((route, view_class.__name__))

    assert class_level_opt_outs and action_level_opt_outs, (
        "the URL walk found no opt-out of one kind; the check below would be vacuous"
    )
    assert gated_by_org_permission == []
    assert scoped_by_org_mixin == []
