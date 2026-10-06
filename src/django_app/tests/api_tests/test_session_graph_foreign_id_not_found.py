"""A session or graph id owned by another organization must answer exactly like a
missing id on the plain session/graph endpoints (run-session, run-session SSE
stream, get-updates, stop). A different status or body would confirm the row
exists. A member of the owning org whose role lacks the permission still gets 403.
"""

import uuid

import pytest
from asgiref.sync import async_to_sync
from django.db.models import Max
from django.test import Client
from django.urls import reverse
from rest_framework import status

from rbac.identity.tickets import sse_ticket_service
from rbac.models import OrganizationUser, Role
from tables.models import Graph, PythonCode, Session, StartNode
from tables.models.graph_models import Edge, PythonNode
from tables.views.sse_views import RunSessionSSEView
from tests.fixtures import redis_client_mock  # noqa: F401
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def _runnable_graph(name: str, org) -> Graph:
    graph = Graph.objects.create(name=name, org=org)
    start = StartNode.objects.create(graph=graph, variables={})
    python_code = PythonCode.objects.create(
        code="def main(**kwargs):\n    return None\n", entrypoint="main"
    )
    node = PythonNode.objects.create(graph=graph, python_code=python_code, node_name="py_node")
    Edge.objects.create(graph=graph, start_node_id=start.pk, end_node_id=node.pk)
    return graph


@pytest.fixture
def graph_in_beta(beta):
    return _runnable_graph("beta-flow-foreign-id", beta)


@pytest.fixture
def graph_in_acme(acme):
    return _runnable_graph("acme-flow-foreign-id", acme)


@pytest.fixture
def session_in_beta(graph_in_beta):
    return Session.objects.create(graph=graph_in_beta, status=Session.SessionStatus.RUN)


@pytest.fixture
def session_in_acme(graph_in_acme):
    return Session.objects.create(graph=graph_in_acme, status=Session.SessionStatus.RUN)


@pytest.fixture
def no_flows_acme(db, django_user_model, acme):
    """Member of Acme whose custom role holds no permissions at all."""
    role = Role.objects.create(name="NoFlows-foreign-id", org=acme, is_built_in=False)
    user = django_user_model.objects.create_user(
        email="no-flows-foreign-id@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role)
    return user


def _missing_session_id() -> int:
    return (Session.objects.aggregate(max_id=Max("id"))["max_id"] or 0) + 1000


def _missing_graph_id() -> int:
    return (Graph.objects.aggregate(max_id=Max("id"))["max_id"] or 0) + 1000


def _status_and_body(response):
    return response.status_code, response.content


# ── POST /api/run-session/ ───────────────────────────────────────────────────


@pytest.mark.django_db
def test_run_session_foreign_graph_id_answers_like_missing(client_as, member_only, graph_in_beta):
    client = client_as(member_only)
    url = reverse("run-session")

    foreign = client.post(url, {"graph_id": graph_in_beta.id}, format="json")
    missing = client.post(url, {"graph_id": _missing_graph_id()}, format="json")

    assert foreign.status_code == status.HTTP_404_NOT_FOUND, foreign.content
    assert _status_and_body(foreign) == _status_and_body(missing)
    assert not Session.objects.filter(graph=graph_in_beta).exists()


@pytest.mark.django_db
def test_run_session_foreign_graph_uuid_answers_like_missing(
    client_as, member_only, graph_in_beta
):
    client = client_as(member_only)
    url = reverse("run-session")

    foreign = client.post(url, {"graph_uuid": str(graph_in_beta.uuid)}, format="json")
    missing = client.post(url, {"graph_uuid": str(uuid.uuid4())}, format="json")

    assert foreign.status_code == status.HTTP_404_NOT_FOUND, foreign.content
    assert _status_and_body(foreign) == _status_and_body(missing)


@pytest.mark.django_db
def test_run_session_member_lacking_flows_read_gets_403(client_as, no_flows_acme, graph_in_acme):
    response = client_as(no_flows_acme).post(
        reverse("run-session"), {"graph_id": graph_in_acme.id}, format="json"
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    assert not Session.objects.filter(graph=graph_in_acme).exists()


@pytest.mark.django_db
def test_run_session_member_of_owning_org_starts_session(
    client_as, member_only, graph_in_acme, redis_client_mock  # noqa: F811
):
    response = client_as(member_only).post(
        reverse("run-session"), {"graph_id": graph_in_acme.id, "variables": {}}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert Session.objects.get(pk=response.data["session_id"]).graph_id == graph_in_acme.id


@pytest.mark.django_db
def test_run_session_superadmin_runs_any_orgs_graph(
    client_as, superadmin, graph_in_beta, redis_client_mock  # noqa: F811
):
    response = client_as(superadmin).post(
        reverse("run-session"), {"graph_id": graph_in_beta.id, "variables": {}}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content


# ── GET /api/sessions/<id>/get-updates/ ──────────────────────────────────────


@pytest.mark.django_db
def test_get_updates_foreign_session_answers_like_missing(client_as, member_only, session_in_beta):
    client = client_as(member_only)

    foreign = client.get(reverse("get-updates", args=[session_in_beta.id]))
    missing = client.get(reverse("get-updates", args=[_missing_session_id()]))

    assert foreign.status_code == status.HTTP_404_NOT_FOUND, foreign.content
    assert _status_and_body(foreign) == _status_and_body(missing)


@pytest.mark.django_db
def test_get_updates_member_of_owning_org_reads_status(client_as, member_only, session_in_acme):
    response = client_as(member_only).get(reverse("get-updates", args=[session_in_acme.id]))

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data == {"status": Session.SessionStatus.RUN}


@pytest.mark.django_db
def test_get_updates_member_lacking_flows_read_gets_403(client_as, no_flows_acme, session_in_acme):
    response = client_as(no_flows_acme).get(reverse("get-updates", args=[session_in_acme.id]))

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content


@pytest.mark.django_db
def test_get_updates_superadmin_reads_any_orgs_session(client_as, superadmin, session_in_beta):
    response = client_as(superadmin).get(reverse("get-updates", args=[session_in_beta.id]))

    assert response.status_code == status.HTTP_200_OK, response.content


# ── POST /api/sessions/<id>/stop/ ────────────────────────────────────────────


@pytest.mark.django_db
def test_stop_foreign_session_answers_like_missing(
    client_as, member_only, session_in_beta, redis_client_mock  # noqa: F811
):
    client = client_as(member_only)

    foreign = client.post(reverse("stop-session", args=[session_in_beta.id]))
    missing = client.post(reverse("stop-session", args=[_missing_session_id()]))

    assert foreign.status_code == status.HTTP_404_NOT_FOUND, foreign.content
    assert _status_and_body(foreign) == _status_and_body(missing)
    redis_client_mock.publish.assert_not_called()


@pytest.mark.django_db
def test_stop_member_of_owning_org_stops_session(
    client_as, member_only, session_in_acme, redis_client_mock  # noqa: F811
):
    response = client_as(member_only).post(reverse("stop-session", args=[session_in_acme.id]))

    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
    redis_client_mock.publish.assert_called_once()


@pytest.mark.django_db
def test_stop_member_lacking_flows_read_gets_403(
    client_as, no_flows_acme, session_in_acme, redis_client_mock  # noqa: F811
):
    response = client_as(no_flows_acme).post(reverse("stop-session", args=[session_in_acme.id]))

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    redis_client_mock.publish.assert_not_called()


# ── GET /api/run-session/subscribe/<id>/ (SSE) ───────────────────────────────


def _subscribe(user, session_id: int):
    ticket, _ = sse_ticket_service.issue(user)
    url = reverse("run-session-subscribe", args=[session_id])
    return Client().get(url, {"ticket": ticket})


@pytest.mark.django_db
def test_sse_foreign_session_answers_like_missing(member_only, session_in_beta):
    foreign = _subscribe(member_only, session_in_beta.id)
    missing = _subscribe(member_only, _missing_session_id())

    assert foreign.status_code == status.HTTP_404_NOT_FOUND, foreign.content
    assert _status_and_body(foreign) == _status_and_body(missing)


@pytest.mark.django_db
def test_sse_member_lacking_flows_read_gets_403(no_flows_acme, session_in_acme):
    response = _subscribe(no_flows_acme, session_in_acme.id)

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content


def _authorize(user, session_id: int):
    view = RunSessionSSEView()
    view.user = user
    view.kwargs = {"session_id": session_id}
    return async_to_sync(view.authorize)(request=None)


@pytest.mark.django_db
def test_sse_member_of_owning_org_is_authorized(member_only, session_in_acme):
    assert _authorize(member_only, session_in_acme.id) is None


@pytest.mark.django_db
def test_sse_superadmin_is_authorized_on_any_orgs_session(superadmin, session_in_beta):
    assert _authorize(superadmin, session_in_beta.id) is None
