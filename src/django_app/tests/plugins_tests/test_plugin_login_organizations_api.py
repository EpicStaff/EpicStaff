"""GET /api/plugins/{identifier}/login-organizations/: the chooser's list of the caller's organizations."""

import pytest
from plugins.identity.plugin_login_tokens import issue_plugin_login_token
from plugins.models import Plugin, PluginState
from rbac.models import Organization, OrganizationUser
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("login_platform")]

URL = "/api/plugins/weather/login-organizations/"


@pytest.fixture
def weather_in_acme_and_beta(loginable_weather, grant_to, acme, beta):
    grant_to(loginable_weather, acme)
    grant_to(loginable_weather, beta)
    return loginable_weather


def test_a_member_gets_the_plugin_and_their_eligible_organizations(client_as, member_only, acme, weather_in_acme_and_beta):
    response = client_as(member_only).get(URL)

    assert response.status_code == 200
    assert response.json() == {
        "plugin": {"identifier": "weather", "name": "Weather", "icon_url": "/api/plugin-public/weather/icon/?v=0.2.0"},
        "organizations": [{"id": acme.pk, "name": acme.name}],
    }


def test_the_list_is_the_caller_s_own_sorted_by_name_never_another_s(
    client_as, member_only, make_member, role_member, role_viewer, acme, beta, weather_in_acme_and_beta, grant_to
):
    alpha = Organization.objects.create(name="alpha-chooser")
    grant_to(weather_in_acme_and_beta, alpha)
    OrganizationUser.objects.create(user=member_only, org=alpha, role=role_member)
    hidden = Organization.objects.create(name="hidden-chooser")
    grant_to(weather_in_acme_and_beta, hidden)
    OrganizationUser.objects.create(user=member_only, org=hidden, role=role_viewer)
    make_member(beta, role_member, "beta-only-chooser@example.com")

    organizations = client_as(member_only).get(URL).json()["organizations"]

    assert organizations == [{"id": acme.pk, "name": acme.name}, {"id": alpha.pk, "name": alpha.name}]


def test_a_member_of_another_organization_sees_only_their_own(client_as, make_member, role_member, beta, weather_in_acme_and_beta):
    beta_member = make_member(beta, role_member, "beta-member-chooser@example.com")

    assert client_as(beta_member).get(URL).json()["organizations"] == [{"id": beta.pk, "name": beta.name}]


def test_the_organization_header_plays_no_part(client_as, member_only, acme, beta, weather_in_acme_and_beta):
    client = client_as(member_only)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(beta.pk))

    assert client.get(URL).json()["organizations"] == [{"id": acme.pk, "name": acme.name}]


def test_a_superadmin_who_is_a_member_nowhere_gets_an_empty_list(client_as, superadmin, weather_in_acme_and_beta):
    response = client_as(superadmin).get(URL)

    assert response.status_code == 200
    assert response.json()["organizations"] == []


def test_the_system_key_gets_an_empty_list(issue_api_key, weather_in_acme_and_beta):
    raw_key, _ = issue_api_key()
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key)

    assert client.get(URL).json()["organizations"] == []


def test_a_member_s_api_key_sees_what_the_member_sees(issue_api_key, member_only, acme, weather_in_acme_and_beta):
    raw_key, _ = issue_api_key(user=member_only)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key)

    assert client.get(URL).json()["organizations"] == [{"id": acme.pk, "name": acme.name}]


def test_a_jwt_caller_is_accepted(member_only, acme, weather_in_acme_and_beta):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(member_only).access_token}")

    assert client.get(URL).json()["organizations"] == [{"id": acme.pk, "name": acme.name}]


def test_anonymous_callers_and_plugin_login_tokens_are_not_authenticated(member_only, acme, weather_in_acme_and_beta):
    token = issue_plugin_login_token(user=member_only, org_id=acme.pk, grant_id=1, identifier="weather").token
    with_token = APIClient()
    with_token.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    assert APIClient().get(URL).status_code == 401
    assert with_token.get(URL).status_code == 401


def test_an_unknown_plugin_is_not_found(client_as, member_only, weather_in_acme_and_beta):
    response = client_as(member_only).get("/api/plugins/missing/login-organizations/")

    assert response.status_code == 404
    assert response.json()["code"] == "plugin_not_found"


def test_a_plugin_that_is_not_running_is_not_found(client_as, member_only, weather_in_acme_and_beta):
    Plugin.objects.filter(pk=weather_in_acme_and_beta.pk).update(state=PluginState.MAINTENANCE)

    assert client_as(member_only).get(URL).status_code == 404


def test_a_plugin_without_a_backend_is_not_found(client_as, member_only, running_plugin, acme, grant_to):
    grant_to(running_plugin(), acme)

    response = client_as(member_only).get(URL)

    assert (response.status_code, response.json()["code"]) == (404, "plugin_not_found")
