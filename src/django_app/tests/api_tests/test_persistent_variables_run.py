import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from tables.models.graph_models import Graph, GraphOrganization, StartNode
from tables.models.session_models import Session
from tables.services.session_manager_service import SessionManagerService


@pytest.fixture
def org_client(regular_user, default_org):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))
    return client


def _flow(default_org, *, flag, org_paths, defaults, org_stored=None):
    graph = Graph.objects.create(
        name="run", org=default_org, enable_persistent_variables=flag
    )
    StartNode.objects.create(
        graph=graph,
        variables={
            "variables": defaults,
            "persistent_variables": {"organization": org_paths, "user": []},
        },
    )
    GraphOrganization.objects.create(graph=graph, persistent_variables=org_stored or {})
    return graph


class _FakeGraphDump:
    def model_dump(self, mode=None):
        return {}


class _FakeSessionData:
    graph = _FakeGraphDump()


@pytest.mark.django_db
def test_run_merges_org_variables_into_session(org_client, default_org, monkeypatch):
    graph = _flow(
        default_org,
        flag=True,
        org_paths=["counter"],
        defaults={"counter": 0},
        org_stored={"counter": 5},
    )
    # run_session publishes to Redis and builds SessionData; stub both so the
    # run completes without the live stack, leaving the merged session to inspect.
    svc = SessionManagerService()
    monkeypatch.setattr(svc, "create_session_data", lambda session: _FakeSessionData())
    monkeypatch.setattr(
        svc.redis_service, "publish_session_data", lambda session_data, org_id: 2
    )

    resp = org_client.post(
        reverse("run-session"), {"graph_id": graph.id, "variables": {}}, format="json"
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.content
    session = Session.objects.get(id=resp.data["session_id"])
    assert session.variables.get("counter") == 5


@pytest.mark.django_db
def test_run_forbidden_for_non_member(default_org):
    graph = _flow(default_org, flag=False, org_paths=[], defaults={})
    outsider = get_user_model().objects.create_user(
        email="outsider@example.com", password="OutsiderPass123!"
    )
    client = APIClient()
    client.force_authenticate(user=outsider)

    resp = client.post(
        reverse("run-session"), {"graph_id": graph.id, "variables": {}}, format="json"
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.content


@pytest.mark.django_db
def test_domain_save_seeds_storage_and_flips_flag(org_client, default_org):
    graph = Graph.objects.create(name="domain", org=default_org)
    GraphOrganization.objects.create(graph=graph)
    sn = StartNode.objects.create(graph=graph, variables={"variables": {"counter": 0}})

    url = reverse("startnode-detail", args=[sn.id])
    resp = org_client.patch(
        url,
        {
            "variables": {
                "variables": {"counter": 0},
                "persistent_variables": {"organization": ["counter"], "user": []},
            }
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK, resp.content
    graph.refresh_from_db()
    assert graph.enable_persistent_variables is True
    assert GraphOrganization.objects.get(graph=graph).persistent_variables == {
        "counter": 0
    }


@pytest.mark.django_db
def test_domain_save_null_default_is_valid(org_client, default_org):
    graph = Graph.objects.create(name="domain-null", org=default_org)
    GraphOrganization.objects.create(graph=graph)
    sn = StartNode.objects.create(
        graph=graph, variables={"variables": {"context": None}}
    )
    url = reverse("startnode-detail", args=[sn.id])
    resp = org_client.patch(
        url,
        {
            "variables": {
                "variables": {"context": None},
                "persistent_variables": {"organization": ["context"], "user": []},
            }
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK, resp.content
    assert GraphOrganization.objects.get(graph=graph).persistent_variables == {
        "context": None
    }


@pytest.mark.django_db
def test_domain_save_rejects_undeclared_path(org_client, default_org):
    graph = Graph.objects.create(name="domain-bad", org=default_org)
    GraphOrganization.objects.create(graph=graph)
    sn = StartNode.objects.create(graph=graph, variables={"variables": {"counter": 0}})
    url = reverse("startnode-detail", args=[sn.id])
    resp = org_client.patch(
        url,
        {
            "variables": {
                "variables": {"counter": 0},
                "persistent_variables": {"organization": ["ghost"], "user": []},
            }
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content
