"""A USER API key is refused at authentication (401) once it is no longer valid for
its org: the org was deactivated (whoever owns the key, a superadmin too), or the
owner is not a superadmin and holds no membership there any more. Superadmin
permission paths never look at the org again, so this is the only gate they meet.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from rbac.models import OrganizationUser
from tables.models import Graph, Session
from tests.fixtures import redis_client_mock  # noqa: F401
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

DEAD_KEY_MESSAGE = "API key is no longer valid for its organization"

ENDPOINTS = [
    ("post", "/api/run-session/", "run-session"),
    ("post", "/api/auth/sse-ticket/", "sse-ticket"),
    ("get", "/api/admin/users/", "admin-users"),
    ("get", "/api/profile/", "profile"),
]


def _key_client(issue_api_key, user, org):
    raw_key, _ = issue_api_key(user=user, org=org)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key)
    return client


def _call(client, method, url, graph):
    if method == "post":
        return client.post(url, {"graph_id": graph.pk}, format="json")
    return client.get(url)


@pytest.fixture
def acme_graph(acme):
    return Graph.objects.create(name="acme flow", org=acme)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "url"),
    [(method, url) for method, url, _ in ENDPOINTS],
    ids=[name for *_, name in ENDPOINTS],
)
def test_superadmin_key_of_deactivated_org_is_401(
    issue_api_key, superadmin, acme, acme_graph, method, url, redis_client_mock
):
    client = _key_client(issue_api_key, superadmin, acme)
    acme.is_active = False
    acme.save(update_fields=["is_active"])

    response = _call(client, method, url, acme_graph)

    assert response.status_code == 401, response.content
    assert response.json()["message"] == DEAD_KEY_MESSAGE


@pytest.mark.django_db
def test_superadmin_key_of_deactivated_org_starts_no_session(
    issue_api_key, superadmin, acme, acme_graph, redis_client_mock
):
    client = _key_client(issue_api_key, superadmin, acme)
    acme.is_active = False
    acme.save(update_fields=["is_active"])

    client.post(reverse("run-session"), {"graph_id": acme_graph.pk}, format="json")

    assert not Session.objects.filter(graph=acme_graph).exists()


@pytest.mark.django_db
def test_key_of_owner_whose_membership_was_deleted_is_401(issue_api_key, member_only, acme):
    client = _key_client(issue_api_key, member_only, acme)
    OrganizationUser.objects.filter(user=member_only, org=acme).delete()

    response = client.get("/api/profile/")

    assert response.status_code == 401, response.content
    assert response.json()["message"] == DEAD_KEY_MESSAGE


@pytest.mark.django_db
@pytest.mark.parametrize("owner", ["member_only", "superadmin"])
def test_key_of_active_org_still_works(request, issue_api_key, owner, acme):
    client = _key_client(issue_api_key, request.getfixturevalue(owner), acme)

    response = client.get("/api/profile/")

    assert response.status_code == 200, response.content
    assert response.json()["active_organization_id"] == acme.id


@pytest.mark.django_db
def test_system_key_is_unaffected_by_deactivated_orgs(issue_api_key, acme):
    raw_key, _ = issue_api_key(user=None, name="system")
    acme.is_active = False
    acme.save(update_fields=["is_active"])
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key)

    response = client.get("/api/auth/api-key/validate/")

    assert response.status_code == 200, response.content
