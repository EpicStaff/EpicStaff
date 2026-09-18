import pytest
from rest_framework.test import APIClient

from tables.models import Graph
from tables.models.graph_models import StartNode
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


# ---- fixtures ----


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


@pytest.fixture
def member_a(db, django_user_model, org_a, role_member):
    user = django_user_model.objects.create_user(
        email="member_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role_member)
    return user


@pytest.fixture
def client_a(member_a, org_a):
    client = APIClient()
    client.force_authenticate(user=member_a)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return client


def _results(resp):
    body = resp.data
    return body["results"] if isinstance(body, dict) and "results" in body else body


# ---- Graph (FLOWS) ----


@pytest.mark.django_db
def test_graph_create_lands_in_active_org(client_a, org_a):
    resp = client_a.post("/api/graphs/", {"name": "Onboarding"}, format="json")
    assert resp.status_code == 201
    assert Graph.objects.get(id=resp.data["id"]).org_id == org_a.id


@pytest.mark.django_db
def test_graph_list_only_active_org(client_a, org_a, org_b):
    Graph.objects.create(name="A flow", org=org_a)
    Graph.objects.create(name="B flow", org=org_b)
    resp = client_a.get("/api/graphs/")
    assert resp.status_code == 200
    names = {g["name"] for g in _results(resp)}
    assert "A flow" in names
    assert "B flow" not in names


@pytest.mark.django_db
def test_graph_detail_cross_org_returns_404(client_a, org_b):
    other = Graph.objects.create(name="B flow", org=org_b)
    resp = client_a.get(f"/api/graphs/{other.id}/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_two_orgs_can_share_a_graph_name(client_a, org_a, org_b):
    Graph.objects.create(name="Shared", org=org_b)
    resp = client_a.post("/api/graphs/", {"name": "Shared"}, format="json")
    assert resp.status_code == 201


@pytest.mark.django_db
def test_graph_request_without_org_header_is_rejected(member_a):
    client = APIClient()
    client.force_authenticate(user=member_a)
    resp = client.get("/api/graphs/")
    assert resp.status_code == 400  # org_context_required


# ---- Child (graph node scoped via parent) ----


@pytest.mark.django_db
def test_node_detail_cross_org_returns_404(client_a, org_b):
    other_graph = Graph.objects.create(name="B flow", org=org_b)
    node = StartNode.objects.create(graph=other_graph, variables={})
    resp = client_a.get(f"/api/startnodes/{node.id}/")
    assert resp.status_code == 404
