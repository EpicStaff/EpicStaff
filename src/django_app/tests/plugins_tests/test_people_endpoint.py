"""`/api/plugin-runtime/`: what a plugin's backend learns about itself and about people."""

import pytest
from epicstaff_plugin.contracts.service_account_api import (
    PeopleLookupResponse,
    PluginPerson,
    ServiceAccountInfo,
)
from plugins.models import GrantState, PluginGrant
from rbac.models import Organization, OrganizationUser
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from tests.plugins_tests.conftest import service_account_client

pytestmark = [pytest.mark.django_db]

ME_URL = "/api/plugin-runtime/me/"
LOOKUP_URL = "/api/plugin-runtime/people/lookup/"
# Weather with a second action only Org Admins get, so plugin permissions have an order.
USER_PERMISSIONS = [
    {"action": "read", "description": "Open Weather.", "defaults": {"org_admin": True, "member": True, "viewer": False}},
    {"action": "delete", "description": "Change the organization's settings.", "defaults": {"org_admin": True, "member": False, "viewer": False}},
]


def _person_url(user_id):
    return f"/api/plugin-runtime/people/{user_id}/"


@pytest.fixture
def weather(weather_backend):
    return weather_backend(user_permissions=USER_PERMISSIONS)


@pytest.fixture
def client(weather, service_account_key, acme):
    return service_account_client(service_account_key(weather, acme), acme)


def _my_permissions(user, organization):
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
        HTTP_X_ORGANIZATION_ID=str(organization.pk),
    )
    return client.get("/api/permissions/me/").json()["permissions"]


# ---- one person ----


def test_an_eligible_member_comes_with_plugin_and_epicstaff_permissions(client, member_only, acme):
    response = client.get(_person_url(member_only.pk))

    assert response.status_code == 200
    person = PluginPerson.model_validate(response.json())
    assert person.user.id == member_only.pk
    assert person.user.email == member_only.email
    assert person.user.name == member_only.effective_display_name
    assert (person.organization.id, person.organization.name) == (acme.pk, acme.name)
    assert person.plugin_permissions == ["read"]
    assert person.epicstaff_permissions == _my_permissions(member_only, acme)


def test_plugin_permissions_come_in_manifest_order(client, admin_acme):
    response = client.get(_person_url(admin_acme.pk))

    assert response.json()["plugin_permissions"] == ["read", "delete"]


def test_a_superadmin_member_gets_their_role_s_permissions_never_everything(
    client, acme, role_member, django_user_model
):
    superadmin_member = django_user_model.objects.create_user(
        email="super-member@example.com", password="StrongPass123!", is_superadmin=True
    )
    OrganizationUser.objects.create(user=superadmin_member, org=acme, role=role_member)

    body = client.get(_person_url(superadmin_member.pk)).json()

    assert body["epicstaff_permissions"] != "*"
    assert body["epicstaff_permissions"] == _my_permissions(
        _plain_member_with_role(django_user_model, acme, role_member), acme
    )


def _plain_member_with_role(django_user_model, organization, role):
    user = django_user_model.objects.create_user(email="plain-member@example.com", password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=organization, role=role)
    return user


@pytest.mark.parametrize("who", ["viewer", "non_member", "inactive", "other_org", "unknown", "too_large"])
def test_anyone_who_may_not_use_the_plugin_is_not_found(
    client, who, acme, beta, role_viewer, role_member, django_user_model, member_only
):
    if who == "viewer":
        user_id = _plain_member_with_role(django_user_model, acme, role_viewer).pk
    elif who == "non_member":
        user_id = django_user_model.objects.create_user(email="stranger@example.com", password="StrongPass123!").pk
    elif who == "inactive":
        django_user_model.objects.filter(pk=member_only.pk).update(is_active=False)
        user_id = member_only.pk
    elif who == "other_org":
        user_id = _plain_member_with_role(django_user_model, beta, role_member).pk
    elif who == "unknown":
        user_id = 999999999
    else:
        user_id = 2**63

    response = client.get(_person_url(user_id))

    assert response.status_code == 404
    assert response.json()["code"] == "person_not_found"


def test_nobody_is_found_while_the_grant_is_not_active(client, member_only):
    PluginGrant.objects.update(state=GrantState.GRANTING)

    assert client.get(_person_url(member_only.pk)).status_code == 404


def test_nobody_is_found_in_an_inactive_organization_s_name(weather, service_account_key, acme, member_only):
    key = service_account_key(weather, acme)
    Organization.objects.filter(pk=acme.pk).update(is_active=False)

    assert service_account_client(key, acme).get(_person_url(member_only.pk)).status_code == 401


# ---- lookup ----


def test_a_lookup_returns_the_eligible_people_sorted_by_user_id(
    client, admin_acme, member_only, acme, role_viewer, django_user_model
):
    viewer = _plain_member_with_role(django_user_model, acme, role_viewer)
    requested = [member_only.pk, viewer.pk, 999999999, admin_acme.pk]

    response = client.post(LOOKUP_URL, {"user_ids": requested}, format="json")

    assert response.status_code == 200
    lookup = PeopleLookupResponse.model_validate(response.json())
    assert [person.user.id for person in lookup.people] == sorted([admin_acme.pk, member_only.pk])


def test_a_lookup_costs_the_same_for_one_person_or_a_hundred(
    client, acme, role_member, django_user_model, django_assert_max_num_queries
):
    people = [
        _plain_member_with_role_named(django_user_model, acme, role_member, index) for index in range(100)
    ]
    client.post(LOOKUP_URL, {"user_ids": [people[0].pk]}, format="json")

    with django_assert_max_num_queries(16):
        response = client.post(LOOKUP_URL, {"user_ids": [person.pk for person in people]}, format="json")

    assert len(response.json()["people"]) == 100


def _plain_member_with_role_named(django_user_model, organization, role, index):
    user = django_user_model.objects.create_user(email=f"member-{index}@example.com", password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=organization, role=role)
    return user


@pytest.mark.parametrize(
    "body",
    [{}, {"user_ids": []}, {"user_ids": list(range(1, 102))}, {"user_ids": [1, 1]}, {"user_ids": [0]}, {"user_ids": ["a"]}],
    ids=["missing", "empty", "over-100", "repeated", "zero", "not-a-number"],
)
def test_a_malformed_lookup_is_invalid(client, body):
    response = client.post(LOOKUP_URL, body, format="json")

    assert response.status_code == 400
    assert response.json()["code"] == "invalid"


# ---- me ----


def test_me_describes_the_service_account(client, weather, acme):
    response = client.get(ME_URL)

    assert response.status_code == 200
    info = ServiceAccountInfo.model_validate(response.json())
    assert info.plugin.identifier == "weather"
    assert info.plugin.version == weather.current_package.version
    assert (info.organization.id, info.organization.name) == (acme.pk, acme.name)
    assert info.grant_state == "active"
    assert info.access == {
        "flows": ["create", "read", "update", "use"],
        "files": ["create", "read"],
        "secrets": ["create", "read", "use"],
        "llm_configs": ["create", "read"],
    }
    assert info.requests_per_minute == 120
    assert info.on_behalf_of is None


def test_me_names_the_person_the_call_is_for(weather, service_account_key, acme, member_only):
    client = service_account_client(service_account_key(weather, acme), acme, on_behalf_of=member_only.pk)

    on_behalf_of = client.get(ME_URL).json()["on_behalf_of"]

    assert on_behalf_of == {"id": member_only.pk, "email": member_only.email, "name": member_only.effective_display_name}


def test_the_organization_comes_from_the_key_without_a_header(weather, service_account_key, acme):
    client = service_account_client(service_account_key(weather, acme))

    assert client.get(ME_URL).json()["organization"]["id"] == acme.pk


def test_another_organization_s_header_is_not_found(weather, service_account_key, acme, beta, member_only):
    client = service_account_client(service_account_key(weather, acme), beta)

    for response in (
        client.get(ME_URL),
        client.get(_person_url(member_only.pk)),
        client.post(LOOKUP_URL, {"user_ids": [member_only.pk]}, format="json"),
    ):
        assert response.status_code == 404
        assert response.json()["code"] == "organization_not_found"


def test_a_person_s_token_is_not_accepted(admin_acme, acme, weather, member_only):
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(admin_acme).access_token}",
        HTTP_X_ORGANIZATION_ID=str(acme.pk),
    )

    for response in (client.get(ME_URL), client.get(_person_url(member_only.pk))):
        assert response.status_code == 401
