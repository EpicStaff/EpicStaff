"""Storage scope a webhook trigger node's code gets from the converter, the same
scope a python node gets: the graph's attached files, then the folders the run
may write to — `sessions/<id>/` in a real run, the caller's extra folder in a
run without a session."""

import pytest

from rbac.models import Organization
from tables.models import Edge, Graph, PythonCode, Session, StartNode
from tables.models.graph_models import GraphStorageFile, StorageFile, WebhookTriggerNode
from tables.services.converter_service import ConverterService
from tables.services.session_manager_service import SessionManagerService


@pytest.fixture
def converter() -> ConverterService:
    return ConverterService()


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org webhook trigger node storage")


@pytest.fixture
def graph(org):
    graph = Graph.objects.create(name="webhook-trigger-node-storage", org=org)
    storage_file = StorageFile.objects.create(org=org, name="input.csv", path="docs/input.csv")
    GraphStorageFile.objects.create(graph=graph, storage_file=storage_file)
    return graph


def _webhook_trigger_node(graph, *, use_storage):
    python_code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    return WebhookTriggerNode.objects.create(
        graph=graph, node_name="webhook_entry", python_code=python_code, use_storage=use_storage
    )


@pytest.mark.django_db
def test_real_run_appends_the_session_folder(converter, org, graph):
    node = _webhook_trigger_node(graph, use_storage=True)

    data = converter.convert_webhook_trigger_node_to_pydantic(
        node, graph_id=graph.pk, session_id=17
    )

    assert data.python_code.use_storage is True
    assert data.python_code.storage_allowed_paths == ["docs/input.csv", "sessions/17/"]
    assert data.python_code.storage_org_prefix == f"org_{org.pk}"
    assert data.python_code.session_id == 17
    assert data.python_code.org_id == org.pk


@pytest.mark.django_db
def test_run_without_session_appends_the_extra_folder(converter, org, graph):
    node = _webhook_trigger_node(graph, use_storage=True)

    data = converter.convert_webhook_trigger_node_to_pydantic(
        node, graph_id=graph.pk, extra_storage_paths=["test-runs/webhook_trigger_node-5/"]
    )

    assert data.python_code.storage_allowed_paths == [
        "docs/input.csv",
        "test-runs/webhook_trigger_node-5/",
    ]
    assert data.python_code.storage_org_prefix == f"org_{org.pk}"
    assert data.python_code.session_id is None


@pytest.mark.django_db
def test_node_without_storage_gets_no_storage_scope(converter, org, graph):
    node = _webhook_trigger_node(graph, use_storage=False)

    data = converter.convert_webhook_trigger_node_to_pydantic(
        node,
        graph_id=graph.pk,
        session_id=17,
        extra_storage_paths=["test-runs/webhook_trigger_node-5/"],
    )

    assert data.python_code.use_storage is False
    assert data.python_code.storage_allowed_paths is None
    assert data.python_code.storage_org_prefix is None
    assert data.python_code.org_id == org.pk


@pytest.mark.django_db
def test_storage_node_without_graph_id_gets_no_storage_scope(converter, graph):
    node = _webhook_trigger_node(graph, use_storage=True)

    data = converter.convert_webhook_trigger_node_to_pydantic(node, session_id=17)

    assert data.python_code.use_storage is True
    assert data.python_code.storage_allowed_paths is None
    assert data.python_code.storage_org_prefix is None
    assert data.python_code.org_id is None


@pytest.mark.django_db
def test_session_graph_data_gives_the_node_its_session_folder(org, graph):
    node = _webhook_trigger_node(graph, use_storage=True)
    # _build_graph_data requires a resolvable entrypoint before it will return.
    start_node = StartNode.objects.create(graph=graph, variables={})
    Edge.objects.create(graph=graph, start_node_id=start_node.id, end_node_id=node.id)
    session = Session.objects.create(
        graph=graph, status=Session.SessionStatus.PENDING, variables={}
    )

    # _build_graph_data has no public wrapper; it is the unit that assembles GraphData.
    graph_data = SessionManagerService()._build_graph_data(
        graph, None, session, start_node=start_node
    )

    [node_data] = graph_data.webhook_trigger_node_data_list
    assert node_data.python_code.storage_allowed_paths == [
        "docs/input.csv",
        f"sessions/{session.pk}/",
    ]
    assert node_data.python_code.storage_org_prefix == f"org_{org.pk}"
    assert node_data.python_code.session_id == session.pk
    assert node_data.python_code.org_id == org.pk
