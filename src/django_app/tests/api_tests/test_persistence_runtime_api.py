import pytest
from django.utils import timezone

from tables.models import (
    Graph,
    PersistenceNode,
    PersistenceTable,
    PersistenceTableEntry,
    Session,
    SubGraphNode,
)
from rbac.models import Organization


def _url(session_id: int, table_id: int, operation: str) -> str:
    return f"/api/internal/sessions/{session_id}/persistence-tables/{table_id}/{operation}/"


@pytest.fixture
def system_client(api_client, env_api_key):
    raw_key, _ = env_api_key
    api_client.credentials(HTTP_X_API_KEY=raw_key)
    return api_client


@pytest.fixture
def table(default_org):
    return PersistenceTable.objects.create(org=default_org, name="Customers")


@pytest.fixture
def running_session(graph, table):
    PersistenceNode.objects.create(graph=graph, node_name="p", persistence_table=table)
    return Session.objects.create(graph=graph, status=Session.SessionStatus.RUN)


@pytest.mark.django_db
def test_write_read_delete_round_trip(system_client, running_session, table):
    written = system_client.post(_url(running_session.id, table.id, "write"),
                                 {"entries": {"a": 1, "b": {"x": [1]}}}, format="json")
    assert written.status_code == 200, written.content
    assert written.data == {"written": 2, "created": ["a", "b"], "table_name": "Customers"}
    assert PersistenceTableEntry.objects.get(table=table, key="a").updated_by_session_id == running_session.id

    read = system_client.post(_url(running_session.id, table.id, "read"), {"keys": ["a", "b", "zz"]}, format="json")
    assert read.data == {"values": {"a": 1, "b": {"x": [1]}}, "table_name": "Customers"}

    rewritten = system_client.post(_url(running_session.id, table.id, "write"),
                                   {"entries": {"a": 2, "c": 3}}, format="json")
    assert rewritten.data == {"written": 2, "created": ["c"], "table_name": "Customers"}

    deleted = system_client.post(_url(running_session.id, table.id, "delete"), {"keys": ["a"]}, format="json")
    assert deleted.data == {"deleted": 1, "table_name": "Customers"}


@pytest.mark.django_db
def test_jwt_user_is_forbidden(auth_client, running_session, table):
    response = auth_client.post(_url(running_session.id, table.id, "read"), {"keys": ["a"]}, format="json")
    assert response.status_code == 403
    assert response.data["code"] == "permission_denied"


@pytest.mark.django_db
def test_user_api_key_is_forbidden(api_client, user_api_key, running_session, table):
    raw_key, _ = user_api_key
    api_client.credentials(HTTP_X_API_KEY=raw_key)
    response = api_client.post(_url(running_session.id, table.id, "read"), {"keys": ["a"]}, format="json")
    assert response.status_code == 403
    assert response.data["code"] == "permission_denied"


@pytest.mark.django_db
@pytest.mark.parametrize("status", [Session.SessionStatus.END, Session.SessionStatus.ERROR,
                                    Session.SessionStatus.STOP, Session.SessionStatus.EXPIRED])
def test_finished_session_is_409(system_client, running_session, table, status):
    running_session.status = status
    running_session.save()
    response = system_client.post(_url(running_session.id, table.id, "read"), {"keys": ["a"]}, format="json")
    assert response.status_code == 409
    assert response.data["code"] == "persistence_session_not_active"


@pytest.mark.django_db
def test_waiting_for_user_session_is_active(system_client, running_session, table):
    running_session.status = Session.SessionStatus.WAIT_FOR_USER
    running_session.save()
    response = system_client.post(_url(running_session.id, table.id, "read"), {"keys": ["a"]}, format="json")
    assert response.status_code == 200


@pytest.mark.django_db
def test_unknown_session_is_404(system_client, table):
    response = system_client.post(_url(999999, table.id, "read"), {"keys": []}, format="json")
    assert response.status_code == 404
    assert response.data["code"] == "not_found"


@pytest.mark.django_db
def test_table_in_other_org_is_404(system_client, running_session):
    foreign = PersistenceTable.objects.create(org=Organization.objects.create(name="Foreign"), name="Customers")
    PersistenceNode.objects.create(graph=running_session.graph, node_name="p2", persistence_table=foreign)
    response = system_client.post(_url(running_session.id, foreign.id, "read"), {"keys": ["a"]}, format="json")
    assert response.status_code == 404
    assert response.data["code"] == "persistence_table_not_found"
    assert "table_name" not in response.data
    assert "Customers" not in response.content.decode()


@pytest.mark.django_db
def test_table_not_referenced_by_graph_is_404(system_client, running_session, default_org):
    other_table = PersistenceTable.objects.create(org=default_org, name="Unreferenced")
    response = system_client.post(_url(running_session.id, other_table.id, "read"), {"keys": ["a"]}, format="json")
    assert response.status_code == 404
    assert response.data["code"] == "persistence_table_not_found"


@pytest.mark.django_db
def test_soft_deleted_node_grants_no_access(system_client, running_session, table):
    PersistenceNode.objects.filter(graph=running_session.graph).update(
        is_soft_deleted=True, soft_deleted_at=timezone.now()
    )
    response = system_client.post(_url(running_session.id, table.id, "read"), {"keys": ["a"]}, format="json")
    assert response.status_code == 404
    assert response.data["code"] == "persistence_table_not_found"


@pytest.mark.django_db
def test_node_in_subgraph_is_accessible(system_client, default_org, table):
    parent = Graph.objects.create(name="Parent", org=default_org)
    child = Graph.objects.create(name="Child", org=default_org)
    SubGraphNode.objects.create(graph=parent, node_name="sub", subgraph=child)
    PersistenceNode.objects.create(graph=child, node_name="p", persistence_table=table)
    session = Session.objects.create(graph=parent, status=Session.SessionStatus.RUN)

    response = system_client.post(_url(session.id, table.id, "write"), {"entries": {"k": 1}}, format="json")
    assert response.status_code == 200, response.content


@pytest.mark.django_db
def test_cyclic_subgraph_references_terminate(system_client, default_org, table):
    parent = Graph.objects.create(name="Parent", org=default_org)
    child = Graph.objects.create(name="Child", org=default_org)
    SubGraphNode.objects.create(graph=parent, node_name="to-child", subgraph=child)
    SubGraphNode.objects.create(graph=child, node_name="to-parent", subgraph=parent)
    session = Session.objects.create(graph=parent, status=Session.SessionStatus.RUN)

    denied = system_client.post(_url(session.id, table.id, "read"), {"keys": ["k"]}, format="json")
    assert denied.status_code == 404

    PersistenceNode.objects.create(graph=child, node_name="p", persistence_table=table)
    allowed = system_client.post(_url(session.id, table.id, "read"), {"keys": ["k"]}, format="json")
    assert allowed.status_code == 200, allowed.content


@pytest.mark.django_db
def test_value_written_by_one_flow_is_read_by_another(system_client, default_org, table):
    writer_graph = Graph.objects.create(name="Writer", org=default_org)
    reader_graph = Graph.objects.create(name="Reader", org=default_org)
    PersistenceNode.objects.create(graph=writer_graph, node_name="w", persistence_table=table, mode="write")
    PersistenceNode.objects.create(graph=reader_graph, node_name="r", persistence_table=table, mode="read")
    writer_session = Session.objects.create(graph=writer_graph, status=Session.SessionStatus.RUN)
    reader_session = Session.objects.create(graph=reader_graph, status=Session.SessionStatus.RUN)

    system_client.post(_url(writer_session.id, table.id, "write"), {"entries": {"shared": "hello"}}, format="json")
    response = system_client.post(_url(reader_session.id, table.id, "read"), {"keys": ["shared"]}, format="json")

    assert response.data == {"values": {"shared": "hello"}, "table_name": "Customers"}


@pytest.mark.django_db
def test_oversized_write_is_400(system_client, running_session, table):
    response = system_client.post(_url(running_session.id, table.id, "write"),
                                  {"entries": {"k": "x" * 262144}}, format="json")
    assert response.status_code == 400
    assert response.data["code"] == "persistence_value_too_large"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "operation, body",
    [
        ("write", {"entries": {"user_4 2": 1}}),
        ("read", {"keys": ["user_4 2"]}),
        ("delete", {"keys": ["user_4 2"]}),
    ],
)
def test_invalid_resolved_key_is_400(system_client, running_session, table, operation, body):
    PersistenceTableEntry.objects.create(table=table, key="user_4 2", value="dev data")

    response = system_client.post(_url(running_session.id, table.id, operation), body, format="json")

    assert response.status_code == 400
    assert response.data["code"] == "persistence_key_invalid"
    assert list(PersistenceTableEntry.objects.filter(table=table).values_list("key", "value")) == [
        ("user_4 2", "dev data")
    ]
