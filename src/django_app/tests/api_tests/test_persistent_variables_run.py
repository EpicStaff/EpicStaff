import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from rbac.models import OrganizationUser
from storage_credentials.services.session_credential_service import (
    session_credential_service,
)
from tables.models.graph_models import Graph, GraphOrganization, StartNode
from tables.models.session_models import Session
from tables.services.session_manager_service import SessionManagerService
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


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


@pytest.fixture
def stub_session_publish(monkeypatch):
    # run_session publishes to Redis and builds SessionData; stub both so the
    # run completes without the live stack, leaving the merged session to inspect.
    svc = SessionManagerService()
    monkeypatch.setattr(
        svc,
        "create_session_data",
        lambda session, token_budget=None, run_type="": _FakeSessionData(),
    )
    monkeypatch.setattr(
        svc.redis_service, "publish_session_data", lambda **kwargs: 2
    )
    monkeypatch.setattr(
        session_credential_service, "issue_for_session", lambda **kwargs: None
    )


@pytest.fixture
def viewer_acme(db, django_user_model, acme, role_viewer):
    user = django_user_model.objects.create_user(
        email="viewer-acme-persistent@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_viewer)
    return user


@pytest.fixture
def counter_flow_acme(acme):
    return _flow(
        acme,
        flag=True,
        org_paths=["counter"],
        defaults={"counter": 0},
        org_stored={"counter": 5},
    )


def _run_counter_flow(client, graph, variables):
    resp = client.post(
        reverse("run-session"),
        {"graph_id": graph.id, "variables": variables},
        format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.content
    return Session.objects.get(id=resp.data["session_id"]).variables


@pytest.mark.django_db
def test_run_merges_org_variables_into_session(
    org_client, default_org, stub_session_publish
):
    graph = _flow(
        default_org,
        flag=True,
        org_paths=["counter"],
        defaults={"counter": 0},
        org_stored={"counter": 5},
    )

    resp = org_client.post(
        reverse("run-session"), {"graph_id": graph.id, "variables": {}}, format="json"
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.content
    session = Session.objects.get(id=resp.data["session_id"])
    assert session.variables.get("counter") == 5


@pytest.mark.django_db
def test_run_as_viewer_takes_declared_org_value_from_storage(
    client_as, viewer_acme, counter_flow_acme, stub_session_publish
):
    variables = _run_counter_flow(
        client_as(viewer_acme), counter_flow_acme, {"counter": 999, "topic": "news"}
    )

    assert variables["counter"] == 5
    assert variables["topic"] == "news"


@pytest.mark.django_db
def test_run_as_viewer_cannot_override_through_nested_variables_wrapper(
    client_as, viewer_acme, counter_flow_acme, stub_session_publish
):
    variables = _run_counter_flow(
        client_as(viewer_acme),
        counter_flow_acme,
        {"variables": {"variables": {"counter": 999}}},
    )

    assert variables["counter"] == 5


@pytest.mark.django_db
def test_run_as_member_with_flows_update_overrides_declared_org_value(
    client_as, member_only, counter_flow_acme, stub_session_publish
):
    variables = _run_counter_flow(client_as(member_only), counter_flow_acme, {"counter": 999})

    assert variables["counter"] == 999


@pytest.mark.django_db
def test_sub_flow_run_with_flows_update_key_takes_declared_org_value_from_storage(
    client_as, member_only, counter_flow_acme, stub_session_publish
):
    parent_session = Session.objects.create(
        graph=counter_flow_acme, status=Session.SessionStatus.RUN
    )
    resp = client_as(member_only).post(
        reverse("run-session"),
        {
            "graph_id": counter_flow_acme.id,
            "variables": {"counter": 999},
            "parent_session_id": parent_session.id,
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.content

    assert Session.objects.get(id=resp.data["session_id"]).variables["counter"] == 5


@pytest.mark.django_db
def test_run_with_viewer_api_key_takes_declared_org_value_from_storage(
    issue_api_key, viewer_acme, counter_flow_acme, stub_session_publish
):
    raw_key, _ = issue_api_key(user=viewer_acme)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key)

    variables = _run_counter_flow(client, counter_flow_acme, {"counter": 999})

    assert variables["counter"] == 5


@pytest.mark.django_db
def test_run_as_viewer_with_flows_update_in_active_org_takes_stored_value(
    client_as, viewer_acme, beta, role_member, counter_flow_acme, stub_session_publish
):
    OrganizationUser.objects.create(user=viewer_acme, org=beta, role=role_member)
    client = client_as(viewer_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(beta.id))

    variables = _run_counter_flow(client, counter_flow_acme, {"counter": 999})

    assert variables["counter"] == 5


@pytest.mark.django_db
def test_run_as_viewer_cannot_seed_unstored_declared_path_through_domain_template(
    client_as, viewer_acme, acme, stub_session_publish
):
    graph = _flow(
        acme,
        flag=True,
        org_paths=["counter"],
        defaults={"counter": "{seed}", "seed": ""},
        org_stored={},
    )

    variables = _run_counter_flow(client_as(viewer_acme), graph, {"seed": "forged"})

    assert variables["counter"] == "{seed}"
    assert variables["seed"] == "forged"


@pytest.mark.django_db
def test_run_hidden_from_non_member(default_org):
    graph = _flow(default_org, flag=False, org_paths=[], defaults={})
    outsider = get_user_model().objects.create_user(
        email="outsider@example.com", password="OutsiderPass123!"
    )
    client = APIClient()
    client.force_authenticate(user=outsider)

    resp = client.post(
        reverse("run-session"), {"graph_id": graph.id, "variables": {}}, format="json"
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND, resp.content


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
