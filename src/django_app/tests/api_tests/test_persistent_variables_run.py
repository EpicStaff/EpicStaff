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
        svc.redis_service, "publish_session_data", lambda session_data: 2
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
