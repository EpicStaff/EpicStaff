"""Every `api/admin/` route either serves a USER API key only its own org's data, or
refuses API keys outright. A new route that is in neither table fails the coverage
check, so it cannot ship without deciding how a key is limited on it."""

import re
from importlib import import_module, reload

import pytest
from django.conf import settings as django_settings
from django.urls import URLResolver, clear_url_caches, get_resolver
from rest_framework import status
from rest_framework.permissions import SAFE_METHODS
from rest_framework.test import APIClient

from rbac.models import OrganizationConfig, OrganizationUser, Role

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

ADMIN_PREFIX = "api/admin/"
HTTP_METHODS = ("get", "post", "put", "patch", "delete")


def _reload_root_urlconf():
    clear_url_caches()
    reload(import_module(django_settings.ROOT_URLCONF))
    clear_url_caches()


@pytest.fixture(autouse=True)
def plugin_routes_mounted(settings):
    """Mount the plugin routes, whatever the environment's PLUGINS_ENABLED says."""
    original = settings.PLUGINS_ENABLED
    settings.PLUGINS_ENABLED = True
    _reload_root_urlconf()
    yield
    settings.PLUGINS_ENABLED = original
    _reload_root_urlconf()


def _admin_routes():
    """Map each `api/admin/` route pattern to the HTTP methods its view serves.

    A router's format-suffix alias (`...\\.(?P<format>...)`) serves the same view as
    the route it repeats, so it is not listed separately.
    """

    def walk(patterns, prefix):
        for pattern in patterns:
            route = prefix + str(pattern.pattern)
            if isinstance(pattern, URLResolver):
                yield from walk(pattern.url_patterns, route)
            else:
                yield route, pattern.callback

    routes = {}
    for route, callback in walk(get_resolver().url_patterns, ""):
        if not route.startswith(ADMIN_PREFIX) or "(?P<format>" in route or ":format>" in route:
            continue
        actions = getattr(callback, "actions", None)
        routes[route] = (
            list(actions)
            if actions
            else [method for method in HTTP_METHODS if hasattr(callback.cls, method)]
        )
    return routes


def _concrete_url(route):
    """Fill a route pattern with placeholder ids: a refusing gate runs before any lookup."""
    url = route.replace("^", "").replace("$", "")
    url = re.sub(r"\(\?P<\w+>\[0-9\]\+\)|<int:\w+>", "1", url)
    url = re.sub(r"<str:\w+>", "weather", url)
    return "/" + url


# --- Scoped: a USER key is admitted and sees only its own org. -------------------------
#
# Each case: (route pattern, request, expected status). The request names Beta every way
# it can; a 200 must carry no Beta row, a read of a Beta row by id is a 404. The status
# is a {owner: status} map where the owner decides it (users are superadmin-only).

OK, NOT_FOUND = status.HTTP_200_OK, status.HTTP_404_NOT_FOUND
SUPERADMIN_ONLY = {"admin_of_both": status.HTTP_403_FORBIDDEN, "superadmin": OK}

SCOPED_CASES = [
    ("api/admin/", lambda c, f: c.get("/api/admin/"), OK),
    ("api/admin/memberships/", lambda c, f: c.get("/api/admin/memberships/", {"org_ids": f.beta.id}), OK),
    ("api/admin/memberships/assignable-users/", lambda c, f: c.get("/api/admin/memberships/assignable-users/"), OK),
    (
        "api/admin/organizations/<int:pk>/retention/",
        lambda c, f: c.get(f"/api/admin/organizations/{f.beta.id}/retention/"),
        NOT_FOUND,
    ),
    ("api/admin/^organizations/$", lambda c, f: c.get("/api/admin/organizations/", {"org_ids": f.beta.id}), OK),
    (
        "api/admin/^organizations/(?P<pk>[0-9]+)/$",
        lambda c, f: c.get(f"/api/admin/organizations/{f.beta.id}/"),
        NOT_FOUND,
    ),
    ("api/admin/^users/$", lambda c, f: c.get("/api/admin/users/", {"org_ids": f.beta.id}), SUPERADMIN_ONLY),
    ("api/admin/^users/$", lambda c, f: c.get("/api/admin/users/", {"organization_id": f.beta.id}), SUPERADMIN_ONLY),
    ("api/admin/^roles/$", lambda c, f: c.get("/api/admin/roles/", {"org_ids": f.beta.id}), OK),
    ("api/admin/^roles/$", lambda c, f: c.get("/api/admin/roles/", {"assignable_org_ids": f.beta.id}), OK),
    ("api/admin/^roles/(?P<pk>[0-9]+)/$", lambda c, f: c.get(f"/api/admin/roles/{f.beta_role.id}/"), NOT_FOUND),
    (
        "api/admin/plugin-role-permissions/rows/",
        lambda c, f: c.get("/api/admin/plugin-role-permissions/rows/", {"org_id": f.beta.id}),
        OK,
    ),
    (
        "api/admin/plugin-role-permissions/<int:role_id>/",
        lambda c, f: c.get(f"/api/admin/plugin-role-permissions/{f.role_member.id}/", {"org_id": f.beta.id}),
        OK,
    ),
    (
        "api/admin/plugin-role-permissions/<int:role_id>/",
        lambda c, f: c.get(f"/api/admin/plugin-role-permissions/{f.beta_role.id}/"),
        NOT_FOUND,
    ),
]

# User-wide surfaces outside `api/admin/` that a USER key must also keep to its org.
USER_WIDE_CASES = [
    lambda c, f: c.get("/api/permissions/me/", HTTP_X_ORGANIZATION_ID=str(f.beta.id)),
    lambda c, f: c.get("/api/permissions/me/orgs/"),
    lambda c, f: c.get("/api/profile/", HTTP_X_ORGANIZATION_ID=str(f.beta.id)),
]

# --- Refused: no API key passes, a superadmin's USER key included. ---------------------

KEY_REFUSED = {
    # Governance writes: JWT-only through `RestrictApiKeyToUserKeyReads`.
    "api/admin/memberships/<int:pk>/",
    "api/admin/organizations/settings/",
    "api/admin/^organizations/(?P<pk>[0-9]+)/deactivate/$",
    "api/admin/^organizations/(?P<pk>[0-9]+)/reactivate/$",
    "api/admin/^users/(?P<pk>[0-9]+)/$",
    "api/admin/^users/(?P<pk>[0-9]+)/deactivate/$",
    "api/admin/^users/(?P<pk>[0-9]+)/grant-superadmin/$",
    "api/admin/^users/(?P<pk>[0-9]+)/reactivate/$",
    "api/admin/^users/(?P<pk>[0-9]+)/revoke-superadmin/$",
    # API keys: `DenyApiKeyAuth`, reads included.
    "api/admin/^api-keys/$",
    "api/admin/^api-keys/(?P<pk>[0-9]+)/$",
    "api/admin/^api-keys/(?P<pk>[0-9]+)/revoke/$",
    # Plugin platform administration: `DenyApiKeyAuth`.
    "api/admin/plugins/",
    "api/admin/plugins/packages/",
    "api/admin/plugins/packages/upload-permission/",
    "api/admin/plugins/packages/<int:package_id>/review/",
    "api/admin/plugins/packages/<int:package_id>/approve/",
    "api/admin/plugins/packages/<int:package_id>/reject/",
    "api/admin/plugins/<str:identifier>/",
    "api/admin/plugins/<str:identifier>/grants/",
    "api/admin/plugins/<str:identifier>/uninstall/",
    "api/admin/plugins/<str:identifier>/reinstall/",
    "api/admin/plugins/<str:identifier>/purge-preview/",
    "api/admin/plugins/<str:identifier>/retry-removal/",
    "api/admin/plugins/<str:identifier>/upgrade/cancel/",
    "api/admin/plugins/<str:identifier>/upgrade/retry/",
    "api/admin/plugins/<str:identifier>/backups/",
    "api/admin/plugins/<str:identifier>/backups/<int:backup_id>/restore/",
    "api/admin/plugins/<str:identifier>/grants/<int:grant_id>/",
    "api/admin/plugins/<str:identifier>/grants/<int:grant_id>/purge-preview/",
    "api/admin/plugins/<str:identifier>/org-removed-jobs/",
    "api/admin/plugins/<str:identifier>/org-removed-jobs/<int:job_id>/retry/",
    "api/admin/plugins/<str:identifier>/org-removed-jobs/<int:job_id>/skip/",
    "api/admin/plugins/<str:identifier>/grants/<int:grant_id>/retry-hook/",
    "api/admin/plugins/<str:identifier>/grants/<int:grant_id>/suspend-preview/",
    "api/admin/plugins/<str:identifier>/grants/<int:grant_id>/suspend/",
    "api/admin/plugins/<str:identifier>/grants/<int:grant_id>/resume/",
    "api/admin/plugins/<str:identifier>/activity/",
    "api/admin/plugins/<str:identifier>/settings/",
    "api/admin/plugins/<str:identifier>/limits/",
    "api/admin/plugins/<str:identifier>/runtime/",
    "api/admin/plugins/<str:identifier>/restart/",
    "api/admin/plugins/<str:identifier>/development/",
    "api/admin/plugins/<str:identifier>/development/runtime-file/",
}


SCOPED_ROUTES = {route for route, _, _ in SCOPED_CASES}


def test_every_admin_route_is_classified():
    classified = SCOPED_ROUTES | KEY_REFUSED
    routes = set(_admin_routes())

    assert not SCOPED_ROUTES & KEY_REFUSED, f"Classified twice: {sorted(SCOPED_ROUTES & KEY_REFUSED)}"
    unclassified = routes - classified
    assert not unclassified, (
        f"Add to SCOPED_CASES (with a USER-key leak check) or KEY_REFUSED: {sorted(unclassified)}"
    )
    assert not classified - routes, f"Stale: {sorted(classified - routes)}"


@pytest.fixture
def admin_of_both(django_user_model, acme, beta, role_org_admin):
    user = django_user_model.objects.create_user(
        email="admin-both-coverage@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_org_admin)
    OrganizationUser.objects.create(user=user, org=beta, role=role_org_admin)
    return user


@pytest.fixture
def beta_only_member(django_user_model, beta, role_member):
    user = django_user_model.objects.create_user(
        email="beta-only-coverage@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=beta, role=role_member)
    return user


@pytest.fixture
def beta_role(beta):
    return Role.objects.create(name="Beta coverage role", org=beta, is_built_in=False)


@pytest.fixture
def key_client(issue_api_key, acme):
    """Factory → a client authenticated by `user`'s USER key bound to Acme."""

    def _make(user):
        raw_key, _ = issue_api_key(user=user, org=acme)
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw_key)
        return client

    return _make


@pytest.fixture
def org_data(acme, beta, beta_role, beta_only_member, role_member):
    """Rows in both orgs, and the Beta strings no Acme-bound key may ever see."""
    OrganizationConfig.objects.create(org=acme)
    OrganizationConfig.objects.create(org=beta)
    data = type("OrgData", (), {})()
    data.acme, data.beta, data.beta_role, data.role_member = acme, beta, beta_role, role_member
    data.beta_markers = [beta.name, beta_role.name, beta_only_member.email]
    return data


def _org_ids_in(data):
    """Every `org_id` value anywhere in a parsed JSON body."""
    if isinstance(data, dict):
        found = [data["org_id"]] if "org_id" in data else []
        return found + [org_id for value in data.values() for org_id in _org_ids_in(value)]
    if isinstance(data, list):
        return [org_id for item in data for org_id in _org_ids_in(item)]
    return []


def _assert_no_beta(response, expected_status, org_data):
    assert response.status_code == expected_status, response.content
    body = response.content.decode()
    leaked = [marker for marker in org_data.beta_markers if marker in body]
    assert not leaked, f"Beta data in an Acme-bound key's response: {leaked}"
    if body:
        assert org_data.beta.id not in _org_ids_in(response.json()), body


@pytest.mark.django_db
@pytest.mark.parametrize("owner", ["admin_of_both", "superadmin"])
@pytest.mark.parametrize(
    "route, make_request, expected_status",
    SCOPED_CASES,
    ids=[f"{index}-{route}" for index, (route, _, _) in enumerate(SCOPED_CASES)],
)
def test_user_key_sees_no_other_org_on_scoped_admin_routes(
    request, key_client, org_data, owner, route, make_request, expected_status
):
    response = make_request(key_client(request.getfixturevalue(owner)), org_data)

    if isinstance(expected_status, dict):
        expected_status = expected_status[owner]
    _assert_no_beta(response, expected_status, org_data)


@pytest.mark.django_db
@pytest.mark.parametrize("owner", ["admin_of_both", "superadmin"])
@pytest.mark.parametrize("make_request", USER_WIDE_CASES, ids=["permissions-me", "permissions-me-orgs", "profile"])
def test_user_key_sees_no_other_org_on_user_wide_routes(request, key_client, org_data, owner, make_request):
    response = make_request(key_client(request.getfixturevalue(owner)), org_data)

    _assert_no_beta(response, status.HTTP_200_OK, org_data)


def _assert_key_refused(client, route, methods):
    url = _concrete_url(route)
    for method in methods:
        response = getattr(client, method)(url)
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        ), f"{method.upper()} {url}: {response.status_code} {response.content!r}"


@pytest.mark.django_db
@pytest.mark.parametrize("route", sorted(KEY_REFUSED))
def test_user_key_is_refused_on_key_refused_routes(key_client, superadmin, route):
    _assert_key_refused(key_client(superadmin), route, _admin_routes()[route])


@pytest.mark.django_db
@pytest.mark.parametrize("route", sorted(SCOPED_ROUTES))
def test_user_key_cannot_write_on_scoped_routes(key_client, superadmin, route):
    writes = [method for method in _admin_routes()[route] if method.upper() not in SAFE_METHODS]

    _assert_key_refused(key_client(superadmin), route, writes)


@pytest.fixture
def beta_admin_acme_member(django_user_model, acme, beta, role_member, role_org_admin):
    """Org Admin in Beta, plain Member in Acme: the door gate passes on Beta's rights."""
    user = django_user_model.objects.create_user(
        email="beta-admin-acme-member@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_member)
    OrganizationUser.objects.create(user=user, org=beta, role=role_org_admin)
    return user


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url_of",
    [
        lambda acme, beta, acme_role: f"/api/admin/roles/{acme_role.id}/",
        lambda acme, beta, acme_role: f"/api/admin/organizations/{acme.id}/",
        lambda acme, beta, acme_role: f"/api/admin/organizations/{beta.id}/",
        lambda acme, beta, acme_role: f"/api/admin/organizations/{acme.id}/retention/",
    ],
    ids=["acme-role", "acme-organization", "beta-organization", "acme-retention"],
)
def test_key_of_a_member_who_administers_another_org_reads_nothing_by_id(
    key_client, beta_admin_acme_member, acme, beta, url_of
):
    OrganizationConfig.objects.create(org=acme)
    acme_role = Role.objects.create(name="Acme coverage role", org=acme, is_built_in=False)

    response = key_client(beta_admin_acme_member).get(url_of(acme, beta, acme_role))

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
