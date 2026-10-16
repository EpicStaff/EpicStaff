"""flows:USE gates starting and stopping a flow run.

POST /api/run-session/ and POST /api/sessions/<id>/stop/ need USE on flows in the
org that owns the flow; READ alone no longer starts or stops a run. A flow in
another org still answers 404, never 403, with or without USE.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from rbac.models import OrganizationUser
from rbac.models.enums import Permission, ResourceType
from tables.models import Graph, PythonCode, Session, StartNode
from tables.models.graph_models import Edge, PythonNode
from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.fixtures import redis_client_mock  # noqa: F401
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

READER = Permission.READ
RUNNER = Permission.READ | Permission.USE
AUTHENTICATION = [
    pytest.param(False, id="session"),
    pytest.param(True, id="user-api-key"),
]


def _runnable_graph(name, org):
    graph = Graph.objects.create(name=name, org=org)
    start = StartNode.objects.create(graph=graph, variables={})
    python_code = PythonCode.objects.create(
        code="def main(**kwargs):\n    return None\n", entrypoint="main"
    )
    node = PythonNode.objects.create(graph=graph, python_code=python_code, node_name="py_node")
    Edge.objects.create(graph=graph, start_node_id=start.pk, end_node_id=node.pk)
    return graph


@pytest.fixture
def acme_graph(acme):
    return _runnable_graph("use-permission-acme-flow", acme)


@pytest.fixture
def beta_graph(beta):
    return _runnable_graph("use-permission-beta-flow", beta)


def _run(client, graph):
    return client.post(
        reverse("run-session"), {"graph_id": graph.id, "variables": {}}, format="json"
    )


def _stop(client, session):
    return client.post(reverse("stop-session", args=[session.id]))


def _running_session(graph):
    return Session.objects.create(graph=graph, status=Session.SessionStatus.RUN)


# ── POST /api/run-session/ ───────────────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.parametrize("via_api_key", AUTHENTICATION)
def test_run_session_with_flows_read_only_gets_403(
    custom_role_client, acme, acme_graph, redis_client_mock, via_api_key  # noqa: F811
):
    client = custom_role_client(acme, {ResourceType.FLOWS: READER}, "reader", via_api_key=via_api_key)

    response = _run(client, acme_graph)

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    assert response.data["code"] == "permission_denied"
    assert not Session.objects.filter(graph=acme_graph).exists()
    redis_client_mock.publish.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize("via_api_key", AUTHENTICATION)
def test_run_session_with_flows_use_starts_session(
    custom_role_client, acme, acme_graph, redis_client_mock, via_api_key  # noqa: F811
):
    client = custom_role_client(acme, {ResourceType.FLOWS: RUNNER}, "runner", via_api_key=via_api_key)

    response = _run(client, acme_graph)

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert Session.objects.get(pk=response.data["session_id"]).graph_id == acme_graph.id


@pytest.mark.django_db
def test_run_session_by_uuid_with_flows_use_starts_session(
    custom_role_client, acme, acme_graph, redis_client_mock  # noqa: F811
):
    client = custom_role_client(acme, {ResourceType.FLOWS: RUNNER}, "runner")

    response = client.post(
        reverse("run-session"),
        {"graph_uuid": str(acme_graph.uuid), "variables": {}},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert Session.objects.get(pk=response.data["session_id"]).graph_id == acme_graph.id


@pytest.mark.django_db
def test_run_session_superadmin_needs_no_role(
    org_client_as, superadmin, acme, acme_graph, redis_client_mock  # noqa: F811
):
    response = _run(org_client_as(superadmin, acme), acme_graph)

    assert response.status_code == status.HTTP_201_CREATED, response.content


@pytest.mark.django_db
@pytest.mark.parametrize("flows_permissions", [READER, RUNNER], ids=["without-use", "with-use"])
def test_run_session_on_foreign_flow_gets_404(
    custom_role_client, acme, beta_graph, redis_client_mock, flows_permissions  # noqa: F811
):
    client = custom_role_client(acme, {ResourceType.FLOWS: flows_permissions}, "acme-caller")

    response = _run(client, beta_graph)

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
    assert response.data["code"] == "graph_not_found"
    assert not Session.objects.filter(graph=beta_graph).exists()
    redis_client_mock.publish.assert_not_called()


@pytest.mark.django_db
def test_run_session_built_in_viewer_cannot_run(
    client_as, django_user_model, acme, role_viewer, acme_graph, redis_client_mock  # noqa: F811
):
    viewer = django_user_model.objects.create_user(
        email="use-perm-viewer@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=viewer, org=acme, role=role_viewer)

    response = _run(client_as(viewer), acme_graph)

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    assert response.data["code"] == "permission_denied"
    assert not Session.objects.filter(graph=acme_graph).exists()
    redis_client_mock.publish.assert_not_called()


# ── POST /api/sessions/<id>/stop/ ────────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.parametrize("via_api_key", AUTHENTICATION)
def test_stop_session_with_flows_read_only_gets_403(
    custom_role_client, acme, acme_graph, redis_client_mock, via_api_key  # noqa: F811
):
    client = custom_role_client(acme, {ResourceType.FLOWS: READER}, "reader", via_api_key=via_api_key)
    session = _running_session(acme_graph)

    response = _stop(client, session)

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    assert response.data["code"] == "permission_denied"
    redis_client_mock.publish.assert_not_called()
    session.refresh_from_db()
    assert session.status == Session.SessionStatus.RUN


@pytest.mark.django_db
@pytest.mark.parametrize("via_api_key", AUTHENTICATION)
def test_stop_session_with_flows_use_stops_it(
    custom_role_client, acme, acme_graph, redis_client_mock, via_api_key  # noqa: F811
):
    client = custom_role_client(acme, {ResourceType.FLOWS: RUNNER}, "runner", via_api_key=via_api_key)

    response = _stop(client, _running_session(acme_graph))

    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
    # The stop request is a Redis publish to the crew and manager services.
    redis_client_mock.publish.assert_called_once()


@pytest.mark.django_db
def test_stop_session_superadmin_needs_no_role(
    org_client_as, superadmin, acme, acme_graph, redis_client_mock  # noqa: F811
):
    response = _stop(org_client_as(superadmin, acme), _running_session(acme_graph))

    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
    redis_client_mock.publish.assert_called_once()


@pytest.mark.django_db
@pytest.mark.parametrize("flows_permissions", [READER, RUNNER], ids=["without-use", "with-use"])
def test_stop_session_on_foreign_session_gets_404(
    custom_role_client, acme, beta_graph, redis_client_mock, flows_permissions  # noqa: F811
):
    client = custom_role_client(acme, {ResourceType.FLOWS: flows_permissions}, "acme-caller")

    response = _stop(client, _running_session(beta_graph))

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
    redis_client_mock.publish.assert_not_called()
