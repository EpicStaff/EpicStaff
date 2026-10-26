"""The bootstrap SuperAdmin's membership (the built-in Superadmin role) uses a plugin as an Org Admin.

Only while its holder is a SuperAdmin: someone whose flag was revoked keeps the membership but
gets nothing through it. And the flag alone still grants nothing: a SuperAdmin who is no member
of an organization may use no plugin there.
"""

import jwt
import pytest
from django.core.cache import cache
from epicstaff_plugin.contracts.service_account_api import PluginPerson
from plugins.access.available_plugins import plugins_available_to
from plugins.access.plugin_access import resolve_person_plugin_access
from plugins.identity.plugin_login_tokens import issue_plugin_login_token
from rbac.models import OrganizationUser, Role
from rbac.models.enums import BuiltInRole
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from tests.plugins_tests.conftest import GATEWAY_SECRET, mark_running, service_account_client
from tests.plugins_tests.login_helpers import authorize, exchange, pkce_pair, redirect_parts, session_cookie

pytestmark = [pytest.mark.django_db]

PERMISSIONS = [
    {"action": "read", "description": "Open it.", "defaults": {"org_admin": True, "member": True, "viewer": False}},
    {"action": "update", "description": "Edit places.", "defaults": {"org_admin": True, "member": True, "viewer": False}},
    {"action": "delete", "description": "Change settings.", "defaults": {"org_admin": True, "member": False, "viewer": False}},
]
ORG_ADMIN_DEFAULTS = ["read", "update", "delete"]


@pytest.fixture
def role_superadmin(db):
    return Role.objects.get(name=BuiltInRole.SUPERADMIN, is_built_in=True, org__isnull=True)


@pytest.fixture
def bootstrap_superadmin(superadmin, acme, role_superadmin):
    """A SuperAdmin with the membership the first setup gives them: the Superadmin role, here in Acme."""
    OrganizationUser.objects.create(user=superadmin, org=acme, role=role_superadmin)
    return superadmin


@pytest.fixture
def demoted_superadmin(superadmin, acme, role_superadmin):
    """A former SuperAdmin: the flag revoked, the Superadmin-role membership still in place."""
    OrganizationUser.objects.create(user=superadmin, org=acme, role=role_superadmin)
    type(superadmin).objects.filter(pk=superadmin.pk).update(is_superadmin=False)
    superadmin.refresh_from_db()
    return superadmin


@pytest.fixture
def weather(backend_plugin, login_platform):
    return mark_running(backend_plugin(user_permissions=PERMISSIONS))


@pytest.fixture
def acme_grant(weather, grant_to, acme):
    return grant_to(weather, acme)


def test_the_superadmin_membership_gets_the_org_admin_defaults(bootstrap_superadmin, acme, weather, acme_grant):
    access = resolve_person_plugin_access(bootstrap_superadmin, acme.pk, weather)

    assert access.actions == ORG_ADMIN_DEFAULTS
    assert [(plugin.plugin.identifier, plugin.permissions) for plugin in plugins_available_to(bootstrap_superadmin, acme.pk)] == [
        ("weather", ORG_ADMIN_DEFAULTS)
    ]


def test_the_superadmin_flag_without_a_membership_still_grants_nothing(superadmin, acme, weather, acme_grant):
    assert resolve_person_plugin_access(superadmin, acme.pk, weather) is None
    assert plugins_available_to(superadmin, acme.pk) == []

    response = authorize(APIClient(), cookie=session_cookie(superadmin))
    _, fragment = redirect_parts(response)
    assert fragment["error"] == "access_denied"


def test_the_superadmin_membership_logs_in_with_the_org_admin_defaults(bootstrap_superadmin, acme_grant):
    client = APIClient()
    verifier, challenge = pkce_pair()
    _, result = redirect_parts(authorize(client, cookie=session_cookie(bootstrap_superadmin), challenge=challenge))

    response = exchange(client, result["code"], verifier)

    assert response.status_code == 200
    assert response.json()["plugin_permissions"] == ORG_ADMIN_DEFAULTS


def _gateway_check(client, user, acme, grant, settings):
    settings.PLUGINS_GATEWAY_SECRET = GATEWAY_SECRET
    cache.delete_pattern("plugins:gw:person:*")
    token = issue_plugin_login_token(user=user, org_id=acme.pk, grant_id=grant.pk, identifier="weather").token
    return client.get(
        "/api/plugin-gateway/check/",
        HTTP_X_PLUGIN_GATEWAY_SECRET=GATEWAY_SECRET,
        HTTP_X_PLUGIN_IDENTIFIER="weather",
        HTTP_X_ORIGINAL_METHOD="GET",
        HTTP_X_ORIGINAL_URI="/api/whoami",
        HTTP_X_ORIGINAL_NORMALIZED_PATH="/api/whoami",
        HTTP_X_REAL_IP="203.0.113.7",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def test_the_gateway_forwards_the_org_admin_defaults(
    bootstrap_superadmin, acme, acme_grant, gateway_in_request_thread, settings, anonymous_client
):
    response = _gateway_check(anonymous_client, bootstrap_superadmin, acme, acme_grant, settings)

    assert response.status_code == 200
    context = jwt.decode(response.headers["X-Plugin-Context"], options={"verify_signature": False})
    assert context["permissions"] == ORG_ADMIN_DEFAULTS
    assert context["user"]["id"] == bootstrap_superadmin.pk


def test_the_roles_matrix_shows_the_superadmin_role_with_the_org_admin_defaults_read_only(
    superadmin_client, role_superadmin, acme, acme_grant
):
    response = superadmin_client.get(f"/api/admin/plugin-role-permissions/{role_superadmin.pk}/", {"org_id": acme.pk})

    assert response.status_code == 200
    body = response.json()
    assert body["editable"] is False
    assert [(row["plugin_identifier"], row["granted"], row["ceiling"]) for row in body["rows"]] == [
        ("weather", ORG_ADMIN_DEFAULTS, [])
    ]


def test_the_people_endpoint_reads_the_superadmin_membership_as_an_org_admin(
    bootstrap_superadmin, admin_acme, acme, weather_backend, service_account_key
):
    # Granted through the grant service, which gives the backend its service account.
    plugin = weather_backend(user_permissions=PERMISSIONS)
    client = service_account_client(service_account_key(plugin, acme), acme)

    response = client.get(f"/api/plugin-runtime/people/{bootstrap_superadmin.pk}/")

    assert response.status_code == 200
    person = PluginPerson.model_validate(response.json())
    assert person.plugin_permissions == ORG_ADMIN_DEFAULTS
    assert person.epicstaff_permissions == _my_permissions(admin_acme, acme)


def _my_permissions(user, organization):
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
        HTTP_X_ORGANIZATION_ID=str(organization.pk),
    )
    return client.get("/api/permissions/me/").json()["permissions"]


# ---- a SuperAdmin whose flag was revoked ----


def test_a_demoted_superadmin_s_membership_gives_no_plugin_action(demoted_superadmin, acme, weather, acme_grant):
    assert resolve_person_plugin_access(demoted_superadmin, acme.pk, weather) is None
    assert plugins_available_to(demoted_superadmin, acme.pk) == []

    _, fragment = redirect_parts(authorize(APIClient(), cookie=session_cookie(demoted_superadmin)))
    assert fragment["error"] == "access_denied"


def test_the_gateway_refuses_a_demoted_superadmin_as_any_member_without_view(
    demoted_superadmin, acme, acme_grant, gateway_in_request_thread, settings, anonymous_client
):
    response = _gateway_check(anonymous_client, demoted_superadmin, acme, acme_grant, settings)

    assert (response.status_code, response.headers.get("X-Plugin-Deny")) == (403, "forbidden")


def test_the_people_endpoint_does_not_know_a_demoted_superadmin(
    demoted_superadmin, acme, weather_backend, service_account_key
):
    plugin = weather_backend(user_permissions=PERMISSIONS)
    client = service_account_client(service_account_key(plugin, acme), acme)

    response = client.get(f"/api/plugin-runtime/people/{demoted_superadmin.pk}/")
    lookup = client.post("/api/plugin-runtime/people/lookup/", {"user_ids": [demoted_superadmin.pk]}, format="json")
    on_behalf = service_account_client(service_account_key(plugin, acme), acme, on_behalf_of=demoted_superadmin.pk)

    assert (response.status_code, response.json()["code"]) == (404, "person_not_found")
    assert lookup.json() == {"people": []}
    assert on_behalf.get("/api/plugin-runtime/me/").json()["code"] == "on_behalf_of_not_allowed"
