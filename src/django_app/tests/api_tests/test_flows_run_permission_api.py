"""flows:RUN gates starting and stopping a flow run.

POST /api/run-session/ and POST /api/sessions/<id>/stop/ need RUN on flows in the
org that owns the flow; READ alone no longer starts or stops a run. A flow in
another org still answers 404, never 403.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tables.models import Graph, PythonCode, Session, StartNode
from tables.models.graph_models import Edge, PythonNode
from tests.fixtures import redis_client_mock  # noqa: F401
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def _runnable_graph(name, org):
    graph = Graph.objects.create(name=name, org=org)
    start = StartNode.objects.create(graph=graph, variables={})
    python_code = PythonCode.objects.create(
        code="def main(**kwargs):\n    return None\n", entrypoint="main"
    )
    node = PythonNode.objects.create(graph=graph, python_code=python_code, node_name="py_node")
    Edge.objects.create(graph=graph, start_node_id=start.pk, end_node_id=node.pk)
    return graph


def _client_with_flows_permissions(client_as, django_user_model, org, permissions, name):
    role = Role.objects.create(name=name, org=org, is_built_in=False)
    RolePermission.objects.create(
        role=role, resource_type=ResourceType.FLOWS, permissions=int(permissions)
    )
    user = django_user_model.objects.create_user(
        email=f"{name}@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def acme_graph(acme):
    return _runnable_graph("run-permission-acme-flow", acme)


@pytest.fixture
def beta_graph(beta):
    return _runnable_graph("run-permission-beta-flow", beta)


@pytest.fixture
def reader_client(client_as, django_user_model, acme):
    return _client_with_flows_permissions(
        client_as, django_user_model, acme, Permission.READ, "run-perm-reader"
    )


@pytest.fixture
def runner_client(client_as, django_user_model, acme):
    return _client_with_flows_permissions(
        client_as, django_user_model, acme, Permission.READ | Permission.RUN, "run-perm-runner"
    )


# ── POST /api/run-session/ ───────────────────────────────────────────────────


@pytest.mark.django_db
def test_run_session_with_flows_read_only_gets_403(
    reader_client, acme_graph, redis_client_mock  # noqa: F811
):
    response = reader_client.post(
        reverse("run-session"), {"graph_id": acme_graph.id, "variables": {}}, format="json"
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    assert response.data["code"] == "permission_denied"
    assert not Session.objects.filter(graph=acme_graph).exists()
    redis_client_mock.publish.assert_not_called()


@pytest.mark.django_db
def test_run_session_with_flows_run_starts_session(
    runner_client, acme_graph, redis_client_mock  # noqa: F811
):
    response = runner_client.post(
        reverse("run-session"), {"graph_id": acme_graph.id, "variables": {}}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert Session.objects.get(pk=response.data["session_id"]).graph_id == acme_graph.id


@pytest.mark.django_db
def test_run_session_by_uuid_with_flows_run_starts_session(
    runner_client, acme_graph, redis_client_mock  # noqa: F811
):
    response = runner_client.post(
        reverse("run-session"),
        {"graph_uuid": str(acme_graph.uuid), "variables": {}},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content


@pytest.mark.django_db
def test_run_session_with_flows_run_on_foreign_flow_gets_404(
    runner_client, beta_graph, redis_client_mock  # noqa: F811
):
    response = runner_client.post(
        reverse("run-session"), {"graph_id": beta_graph.id, "variables": {}}, format="json"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
    assert response.data["code"] == "graph_not_found"
    assert not Session.objects.filter(graph=beta_graph).exists()


@pytest.mark.django_db
def test_run_session_built_in_viewer_can_run(
    client_as, django_user_model, acme, role_viewer, acme_graph, redis_client_mock  # noqa: F811
):
    viewer = django_user_model.objects.create_user(
        email="run-perm-viewer@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=viewer, org=acme, role=role_viewer)

    response = client_as(viewer).post(
        reverse("run-session"), {"graph_id": acme_graph.id, "variables": {}}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content


# ── POST /api/sessions/<id>/stop/ ────────────────────────────────────────────


@pytest.mark.django_db
def test_stop_session_with_flows_read_only_gets_403(
    reader_client, acme_graph, redis_client_mock  # noqa: F811
):
    session = Session.objects.create(graph=acme_graph, status=Session.SessionStatus.RUN)

    response = reader_client.post(reverse("stop-session", args=[session.id]))

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    redis_client_mock.publish.assert_not_called()


@pytest.mark.django_db
def test_stop_session_with_flows_run_stops_it(
    runner_client, acme_graph, redis_client_mock  # noqa: F811
):
    session = Session.objects.create(graph=acme_graph, status=Session.SessionStatus.RUN)

    response = runner_client.post(reverse("stop-session", args=[session.id]))

    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
    redis_client_mock.publish.assert_called_once()


@pytest.mark.django_db
def test_stop_session_with_flows_run_on_foreign_session_gets_404(
    runner_client, beta_graph, redis_client_mock  # noqa: F811
):
    session = Session.objects.create(graph=beta_graph, status=Session.SessionStatus.RUN)

    response = runner_client.post(reverse("stop-session", args=[session.id]))

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
    redis_client_mock.publish.assert_not_called()
