"""Storage scope a python node's code gets from the converter: the graph's
attached files, then the folders the run may write to — `sessions/<id>/` in a
real run, the caller's extra folder in a run without a session."""

import pytest

from rbac.models import Organization
from tables.models import Graph, PythonCode, PythonNode
from tables.models.graph_models import GraphStorageFile, StorageFile
from tables.services.converter_service import ConverterService


@pytest.fixture
def converter() -> ConverterService:
    return ConverterService()


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org python node storage")


@pytest.fixture
def graph(org):
    graph = Graph.objects.create(name="python-node-storage", org=org)
    storage_file = StorageFile.objects.create(org=org, name="input.csv", path="docs/input.csv")
    GraphStorageFile.objects.create(graph=graph, storage_file=storage_file)
    return graph


def _python_node(graph):
    python_code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    return PythonNode.objects.create(graph=graph, python_code=python_code)


@pytest.mark.django_db
def test_real_run_appends_the_session_folder(converter, org, graph):
    node = _python_node(graph)

    data = converter.convert_python_node_to_pydantic(node, graph_id=graph.pk, session_id=17)

    assert data.python_code.use_storage is True
    assert data.python_code.storage_allowed_paths == ["docs/input.csv", "sessions/17/"]
    assert data.python_code.storage_org_prefix == f"org_{org.pk}"
    assert data.python_code.session_id == 17
    assert data.python_code.org_id == org.pk


@pytest.mark.django_db
def test_run_without_session_appends_the_extra_folder(converter, org, graph):
    node = _python_node(graph)

    data = converter.convert_python_node_to_pydantic(
        node, graph_id=graph.pk, extra_storage_paths=["test-runs/python_node-5/"]
    )

    assert data.python_code.storage_allowed_paths == [
        "docs/input.csv",
        "test-runs/python_node-5/",
    ]
    assert data.python_code.storage_org_prefix == f"org_{org.pk}"
    assert data.python_code.session_id is None


@pytest.mark.django_db
def test_node_with_no_box_ticked_still_gets_storage_scope(converter, org, graph):
    node = _python_node(graph)
    assert (node.storage_grant_read, node.storage_grant_write, node.storage_grant_delete) == (
        False,
        False,
        False,
    )

    data = converter.convert_python_node_to_pydantic(node, graph_id=graph.pk, session_id=17)

    assert data.python_code.use_storage is True
    assert data.python_code.storage_allowed_paths == ["docs/input.csv", "sessions/17/"]
    assert data.python_code.storage_org_prefix == f"org_{org.pk}"
    assert data.python_code.storage_grant.model_dump() == {
        "read": False,
        "write": False,
        "delete": False,
    }


@pytest.mark.django_db
def test_node_without_graph_id_gets_no_storage_scope(converter, graph):
    node = _python_node(graph)

    data = converter.convert_python_node_to_pydantic(node, session_id=17)

    assert data.python_code.storage_allowed_paths is None
    assert data.python_code.storage_org_prefix is None


@pytest.mark.django_db
def test_attached_paths_given_by_the_caller_are_used_instead_of_the_graphs(converter, graph):
    node = _python_node(graph)

    data = converter.convert_python_node_to_pydantic(
        node, graph_id=graph.pk, session_id=17, attached_storage_paths=["given/by/caller.csv"]
    )

    assert data.python_code.storage_allowed_paths == ["given/by/caller.csv", "sessions/17/"]
