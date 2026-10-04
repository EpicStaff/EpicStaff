import pytest

from tables.models import Graph
from tables.models.session_models import Session

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

BULK_DELETE_URL = "/api/sessions/bulk_delete/"
EXPORT_ALL_URL = "/api/sessions/export_all/"


@pytest.fixture
def acme_admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def acme_graph(acme):
    return Graph.objects.create(name="acme cascade flow", org=acme)


@pytest.fixture
def beta_graph(beta):
    return Graph.objects.create(name="beta cascade flow", org=beta)


def _make_session(graph, parent: Session | None = None) -> Session:
    return Session.objects.create(
        graph=graph,
        status=Session.SessionStatus.PENDING,
        variables={},
        parent_session=parent,
    )


def _results(response):
    body = response.data
    return body["results"] if isinstance(body, dict) and "results" in body else body


@pytest.mark.django_db
def test_bulk_delete_of_parent_counts_only_requested_sessions_and_removes_subtree(
    acme_admin_client, acme_graph
):
    parent = _make_session(acme_graph)
    child = _make_session(acme_graph, parent=parent)
    grandchild = _make_session(acme_graph, parent=child)

    response = acme_admin_client.post(
        BULK_DELETE_URL, {"ids": [parent.id]}, format="json"
    )

    assert response.status_code == 200, response.data
    assert response.data == {"deleted": 1, "ids": [parent.id]}
    assert not Session.objects.filter(
        id__in=[parent.id, child.id, grandchild.id]
    ).exists()


@pytest.mark.django_db
def test_bulk_delete_counts_each_requested_session_once_when_parent_and_child_requested(
    acme_admin_client, acme_graph
):
    parent = _make_session(acme_graph)
    child = _make_session(acme_graph, parent=parent)
    _make_session(acme_graph, parent=child)
    missing_id = parent.id + 10_000

    response = acme_admin_client.post(
        BULK_DELETE_URL, {"ids": [parent.id, child.id, missing_id]}, format="json"
    )

    assert response.status_code == 200, response.data
    assert response.data["deleted"] == 2
    assert not Session.objects.filter(graph=acme_graph).exists()


@pytest.mark.django_db
def test_bulk_delete_does_not_touch_other_org_parent_or_its_children(
    acme_admin_client, beta_graph
):
    beta_parent = _make_session(beta_graph)
    beta_child = _make_session(beta_graph, parent=beta_parent)

    response = acme_admin_client.post(
        BULK_DELETE_URL, {"ids": [beta_parent.id]}, format="json"
    )

    assert response.status_code == 200, response.data
    assert response.data["deleted"] == 0
    assert Session.objects.filter(id__in=[beta_parent.id, beta_child.id]).count() == 2


@pytest.mark.django_db
def test_session_list_never_contains_child_after_parent_deleted(
    acme_admin_client, acme_graph
):
    parent = _make_session(acme_graph)
    child = _make_session(acme_graph, parent=parent)
    _make_session(acme_graph, parent=child)
    remaining_root = _make_session(acme_graph)

    delete_response = acme_admin_client.delete(f"/api/sessions/{parent.id}/")
    assert delete_response.status_code == 204

    list_response = acme_admin_client.get("/api/sessions/?detailed=false")
    assert list_response.status_code == 200
    listed_ids = {session["id"] for session in _results(list_response)}
    assert listed_ids == {remaining_root.id}


@pytest.mark.django_db
def test_export_all_does_not_select_child_as_top_level_after_parent_deleted(
    acme_admin_client, acme_graph
):
    parent = _make_session(acme_graph)
    _make_session(acme_graph, parent=_make_session(acme_graph, parent=parent))

    delete_response = acme_admin_client.delete(f"/api/sessions/{parent.id}/")
    assert delete_response.status_code == 204

    export_response = acme_admin_client.post(
        EXPORT_ALL_URL, {"graph_id": acme_graph.id}, format="json"
    )
    assert export_response.status_code == 404
