"""`X-EpicStaff-On-Behalf-Of`: a service account names the person a call is for, and EpicStaff checks it."""

import pytest
from plugins.models import GrantState, PluginActivityEvent, PluginGrant, PluginRolePermission
from rbac.models import Organization, OrganizationUser
from rbac.models.enums import Permission
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from tables.models import Graph

from tests.plugins_tests.conftest import service_account_client

pytestmark = [pytest.mark.django_db]

ME_URL = "/api/plugin-runtime/me/"


@pytest.fixture
def weather(weather_backend):
    return weather_backend()


@pytest.fixture
def acme_key(weather, service_account_key, acme):
    return service_account_key(weather, acme)


def _refused(response):
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "on_behalf_of_not_allowed"
    assert body["message"] == "The plugin cannot act on behalf of this person."


def test_a_member_who_may_use_the_plugin_is_accepted(acme_key, acme, member_only):
    response = service_account_client(acme_key, acme, on_behalf_of=member_only.pk).get(ME_URL)

    assert response.status_code == 200
    assert response.json()["on_behalf_of"]["id"] == member_only.pk


def test_a_write_on_behalf_of_a_person_records_them_in_the_activity(acme_key, acme, member_only):
    response = service_account_client(acme_key, acme, on_behalf_of=member_only.pk).post(
        "/api/graphs/", {"name": "Forecast for Ada"}, format="json"
    )

    assert response.status_code == 201
    event = PluginActivityEvent.objects.get(action="api_request")
    assert (event.on_behalf_of_user_id, event.on_behalf_of_label) == (member_only.pk, member_only.email)
    assert event.actor_label == "Weather (plugin)"


def test_the_person_s_own_epicstaff_rights_are_not_consulted(acme_key, acme, django_user_model, make_custom_role):
    # A custom role with View on Weather and nothing in EpicStaff: the plugin's declared
    # access, not the person's rights, caps the call.
    role = make_custom_role(acme, "weather-only")
    person = django_user_model.objects.create_user(email="weather-only@example.com", password="StrongPass123!")
    OrganizationUser.objects.create(user=person, org=acme, role=role)
    PluginRolePermission.objects.create(grant=PluginGrant.objects.get(org=acme), role=role, permissions=int(Permission.READ))

    response = service_account_client(acme_key, acme, on_behalf_of=person.pk).post(
        "/api/graphs/", {"name": "Created for a person without flow rights"}, format="json"
    )

    assert response.status_code == 201
    assert Graph.objects.filter(name="Created for a person without flow rights", org=acme).exists()


@pytest.mark.parametrize("who", ["viewer", "non_member", "deactivated", "other_org", "unknown"])
def test_anyone_who_may_not_use_the_plugin_is_refused_with_one_answer(
    acme_key, acme, beta, who, role_viewer, role_member, django_user_model, member_only
):
    if who == "viewer":
        user = django_user_model.objects.create_user(email="viewer-obo@example.com", password="StrongPass123!")
        OrganizationUser.objects.create(user=user, org=acme, role=role_viewer)
        user_id = user.pk
    elif who == "non_member":
        user_id = django_user_model.objects.create_user(email="stranger-obo@example.com", password="StrongPass123!").pk
    elif who == "deactivated":
        django_user_model.objects.filter(pk=member_only.pk).update(is_active=False)
        user_id = member_only.pk
    elif who == "other_org":
        user = django_user_model.objects.create_user(email="beta-obo@example.com", password="StrongPass123!")
        OrganizationUser.objects.create(user=user, org=beta, role=role_member)
        user_id = user.pk
    else:
        user_id = 987654321

    _refused(service_account_client(acme_key, acme, on_behalf_of=user_id).get(ME_URL))


def test_nobody_is_acted_for_while_the_install_hook_runs(acme_key, acme, member_only):
    PluginGrant.objects.update(state=GrantState.GRANTING)

    _refused(service_account_client(acme_key, acme, on_behalf_of=member_only.pk).get(ME_URL))


def test_a_refusal_writes_nothing(acme_key, acme, django_user_model):
    stranger = django_user_model.objects.create_user(email="stranger-write@example.com", password="StrongPass123!")

    response = service_account_client(acme_key, acme, on_behalf_of=stranger.pk).post(
        "/api/graphs/", {"name": "Never"}, format="json"
    )

    _refused(response)
    assert not Graph.objects.filter(name="Never").exists()
    assert not PluginActivityEvent.objects.filter(action="api_request").exists()


@pytest.mark.parametrize(
    "value",
    ["abc", "-1", "0", "1.5", " 7", "7 ", "", "9223372036854775808", "١", "0x10"],
    ids=["letters", "negative", "zero", "decimal-point", "leading-space", "trailing-space", "empty", "2^63", "arabic-digit", "hex"],
)
def test_a_malformed_value_is_a_bad_request(acme_key, acme, value):
    client = service_account_client(acme_key, acme)
    client.credentials(**{**client._credentials, "HTTP_X_EPICSTAFF_ON_BEHALF_OF": value})

    response = client.get(ME_URL)

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_on_behalf_of"


def test_the_largest_id_is_well_formed(acme_key, acme):
    _refused(service_account_client(acme_key, acme, on_behalf_of=2**63 - 1).get(ME_URL))


def test_the_header_is_ignored_for_a_person_s_token(admin_acme, acme, django_user_model):
    stranger = django_user_model.objects.create_user(email="stranger-jwt@example.com", password="StrongPass123!")
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(admin_acme).access_token}",
        HTTP_X_ORGANIZATION_ID=str(acme.pk),
        HTTP_X_EPICSTAFF_ON_BEHALF_OF=str(stranger.pk),
    )

    assert client.get("/api/graphs/").status_code == 200
    assert client.get("/api/graphs/", HTTP_X_EPICSTAFF_ON_BEHALF_OF="not-a-number").status_code == 200


def test_the_header_is_ignored_for_an_api_key(admin_acme, acme, issue_api_key, django_user_model):
    stranger = django_user_model.objects.create_user(email="stranger-key@example.com", password="StrongPass123!")
    raw_key, _ = issue_api_key(user=admin_acme)
    client = APIClient()
    client.credentials(
        HTTP_X_API_KEY=raw_key,
        HTTP_X_ORGANIZATION_ID=str(acme.pk),
        HTTP_X_EPICSTAFF_ON_BEHALF_OF=str(stranger.pk),
    )

    assert client.get("/api/graphs/").status_code == 200


def test_a_refusal_is_logged_without_the_person_s_details(acme_key, acme, django_user_model, log_messages):
    stranger = django_user_model.objects.create_user(email="stranger-log@example.com", password="StrongPass123!")

    service_account_client(acme_key, acme, on_behalf_of=stranger.pk).get(ME_URL)

    lines = [line for line in log_messages if "plugins.on_behalf_of.refused" in line]
    assert lines == [f"plugins.on_behalf_of.refused plugin=weather org={acme.pk} user_id={stranger.pk}"]
    assert all(stranger.email not in line for line in log_messages)


def test_an_inactive_organization_refuses_the_key_before_the_person_is_checked(acme_key, acme, member_only):
    Organization.objects.filter(pk=acme.pk).update(is_active=False)

    response = service_account_client(acme_key, acme, on_behalf_of=member_only.pk).get(ME_URL)

    assert response.status_code == 401
