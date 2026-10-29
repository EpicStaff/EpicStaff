"""A USER API key acts only in its own org: the X-Organization-Id header is never read."""

import pytest
from rest_framework.test import APIClient

from rbac.models import OrganizationUser
from tables.models import Graph
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

GRAPHS_URL = "/api/graphs/"
PROFILE_URL = "/api/profile/"
DEAD_KEY_MESSAGE = "API key is no longer valid for its organization"


@pytest.fixture
def member_of_both(member_only, beta, role_member):
    """Member of Acme (from `member_only`) and of Beta."""
    OrganizationUser.objects.create(user=member_only, org=beta, role=role_member)
    return member_only


@pytest.fixture
def flows(acme, beta):
    Graph.objects.create(name="acme flow", org=acme)
    Graph.objects.create(name="beta flow", org=beta)


def _key_client(issue_api_key, user, org, header_org=None):
    raw_key, _ = issue_api_key(user=user, org=org)
    headers = {"HTTP_X_API_KEY": raw_key}
    if header_org is not None:
        headers["HTTP_X_ORGANIZATION_ID"] = str(header_org.id)
    client = APIClient()
    client.credentials(**headers)
    return client


def _flow_names(response):
    assert response.status_code == 200, response.content
    return [graph["name"] for graph in response.json()["results"]]


@pytest.mark.django_db
def test_key_without_header_acts_in_its_org(issue_api_key, member_of_both, acme, flows):
    client = _key_client(issue_api_key, member_of_both, acme)

    assert _flow_names(client.get(GRAPHS_URL)) == ["acme flow"]


@pytest.mark.django_db
def test_key_with_other_org_header_still_acts_in_its_org(
    issue_api_key, member_of_both, acme, beta, flows
):
    client = _key_client(issue_api_key, member_of_both, acme, header_org=beta)

    assert _flow_names(client.get(GRAPHS_URL)) == ["acme flow"]


@pytest.mark.django_db
def test_key_with_malformed_header_still_acts_in_its_org(issue_api_key, member_only, acme, flows):
    raw_key, _ = issue_api_key(user=member_only, org=acme)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID="not-a-number")

    assert _flow_names(client.get(GRAPHS_URL)) == ["acme flow"]


@pytest.mark.django_db
def test_key_stops_when_owner_leaves_its_org(issue_api_key, member_of_both, acme, beta, flows):
    client = _key_client(issue_api_key, member_of_both, acme, header_org=beta)
    OrganizationUser.objects.filter(user=member_of_both, org=acme).delete()

    response = client.get(GRAPHS_URL)

    assert response.status_code == 401, response.content
    assert response.json()["message"] == DEAD_KEY_MESSAGE


@pytest.mark.django_db
@pytest.mark.parametrize("owner", ["member_only", "superadmin"])
def test_key_stops_when_its_org_is_deactivated(request, issue_api_key, owner, acme, flows):
    client = _key_client(issue_api_key, request.getfixturevalue(owner), acme)
    acme.is_active = False
    acme.save(update_fields=["is_active"])

    response = client.get(GRAPHS_URL)

    assert response.status_code == 401, response.content
    assert response.json()["message"] == DEAD_KEY_MESSAGE


@pytest.mark.django_db
def test_superadmin_key_acts_in_its_org(issue_api_key, superadmin, acme, beta, flows):
    client = _key_client(issue_api_key, superadmin, beta, header_org=acme)

    assert _flow_names(client.get(GRAPHS_URL)) == ["beta flow"]


@pytest.mark.django_db
@pytest.mark.parametrize("header", ["none", "other-org"])
def test_profile_with_key_reports_key_org_as_active(
    issue_api_key, member_of_both, acme, beta, header
):
    client = _key_client(
        issue_api_key, member_of_both, acme, header_org=beta if header == "other-org" else None
    )

    response = client.get(PROFILE_URL)

    assert response.status_code == 200, response.content
    assert response.json()["active_organization_id"] == acme.id


@pytest.mark.django_db
def test_flow_assistant_with_key_acts_in_key_org_despite_header(
    issue_api_key, member_of_both, acme, beta
):
    acme_flow = Graph.objects.create(name="acme flow", org=acme)
    client = _key_client(issue_api_key, member_of_both, acme, header_org=beta)

    response = client.get(f"/api/flow-assistants/{acme_flow.id}/conversations/")

    assert response.status_code == 200, response.content


ORGS_PERMISSIONS_URL = "/api/permissions/me/orgs/"


@pytest.fixture(params=["member_of_both", "superadmin"])
def owner_of_both(request):
    """Reaches Acme and Beta, through membership or as a superadmin."""
    return request.getfixturevalue(request.param)


def _membership_org_ids(response):
    assert response.status_code == 200, response.content
    return sorted(membership["organization"]["id"] for membership in response.json()["memberships"])


@pytest.mark.django_db
def test_profile_with_key_lists_only_the_key_org(issue_api_key, owner_of_both, acme, beta):
    client = _key_client(issue_api_key, owner_of_both, acme, header_org=beta)

    assert _membership_org_ids(client.get(PROFILE_URL)) == [acme.id]


@pytest.mark.django_db
def test_profile_with_session_lists_every_org(client_as, owner_of_both, acme, beta):
    assert _membership_org_ids(client_as(owner_of_both).get(PROFILE_URL)) == sorted(
        [acme.id, beta.id]
    )


@pytest.mark.django_db
def test_orgs_permissions_with_key_list_only_the_key_org(
    issue_api_key, owner_of_both, acme, beta
):
    client = _key_client(issue_api_key, owner_of_both, acme, header_org=beta)

    response = client.get(ORGS_PERMISSIONS_URL)

    assert response.status_code == 200, response.content
    body = response.json()
    assert [entry["org"]["id"] for entry in body["orgs"]] == [acme.id]
    assert body["is_superadmin"] is owner_of_both.is_superadmin
    assert "permissions" not in body


@pytest.mark.django_db
@pytest.mark.parametrize("owner", ["member_only", "superadmin"])
def test_orgs_permissions_with_key_of_a_deactivated_org_is_401(request, issue_api_key, owner, acme):
    client = _key_client(issue_api_key, request.getfixturevalue(owner), acme)
    acme.is_active = False
    acme.save(update_fields=["is_active"])

    response = client.get(ORGS_PERMISSIONS_URL)

    assert response.status_code == 401, response.content
    assert response.json()["message"] == DEAD_KEY_MESSAGE


@pytest.mark.django_db
def test_orgs_permissions_with_session_are_unchanged(client_as, member_of_both, superadmin, acme, beta):
    member_orgs = client_as(member_of_both).get(ORGS_PERMISSIONS_URL).json()["orgs"]

    assert sorted(entry["org"]["id"] for entry in member_orgs) == sorted([acme.id, beta.id])
    assert client_as(superadmin).get(ORGS_PERMISSIONS_URL).json() == {
        "is_superadmin": True,
        "permissions": "*",
    }
