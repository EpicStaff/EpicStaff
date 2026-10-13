import json

import pytest

from tables.import_export.enums import EntityType
from tables.import_export.serializers.classification_decision_table_node import (
    ClassificationDecisionTableNodeImportSerializer,
)
from tables.models import PythonCode
from tables.models.graph_models import ClassificationDecisionTableNode, Graph

VICTIM_CODE = "def main():\n    return 'shared tool code'"
IMPORTED_CODE = "def main():\n    return 'imported code'"

MISSING = object()


@pytest.fixture
def victim_python_code(db):
    """An existing PythonCode row the import file must never be able to bind to."""
    return PythonCode.objects.create(code=VICTIM_CODE, entrypoint="main", libraries="")


@pytest.fixture
def exported_cdt_graph(default_org, export_service):
    graph = Graph.objects.create(name="cdt-python-code-src", org=default_org)
    ClassificationDecisionTableNode.objects.create(graph=graph, node_name="cdt")
    export_data = json.loads(
        json.dumps(export_service.export_entities(EntityType.GRAPH, [graph.id]))
    )
    yield export_data


def _exported_cdt_node(export_data: dict) -> dict:
    return next(
        node
        for node in export_data[EntityType.GRAPH][0]["nodes"]
        if node["node_type"] == EntityType.CLASSIFICATION_DECISION_TABLE_NODE
    )


def _imported_cdt_node(import_service, export_data: dict) -> ClassificationDecisionTableNode:
    id_mapper, _ = import_service.import_data(export_data, EntityType.GRAPH)
    new_graph_id = id_mapper.get_created_ids(EntityType.GRAPH)[0]
    return ClassificationDecisionTableNode.objects.get(graph_id=new_graph_id)


def _assert_victim_untouched(victim: PythonCode) -> None:
    victim.refresh_from_db()
    assert victim.code == VICTIM_CODE
    assert victim.entrypoint == "main"
    assert not ClassificationDecisionTableNode.objects.filter(
        pre_python_code=victim
    ).exists()
    assert not ClassificationDecisionTableNode.objects.filter(
        post_python_code=victim
    ).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("slot", ["pre", "post"])
@pytest.mark.parametrize("body", [MISSING, None, {}], ids=["no-body", "null-body", "empty-body"])
def test_import_ignores_foreign_python_code_id_without_body(
    slot, body, victim_python_code, exported_cdt_graph, import_service
):
    node_data = _exported_cdt_node(exported_cdt_graph)
    node_data.pop(f"{slot}_python_code", None)
    if body is not MISSING:
        node_data[f"{slot}_python_code"] = body
    node_data[f"{slot}_python_code_id"] = victim_python_code.id
    python_code_count_before = PythonCode.objects.count()

    new_node = _imported_cdt_node(import_service, exported_cdt_graph)

    assert getattr(new_node, f"{slot}_python_code_id") is None
    assert PythonCode.objects.count() == python_code_count_before
    _assert_victim_untouched(victim_python_code)


@pytest.mark.django_db
@pytest.mark.parametrize("slot", ["pre", "post"])
def test_import_creates_fresh_python_code_when_body_and_foreign_id_given(
    slot, victim_python_code, exported_cdt_graph, import_service
):
    node_data = _exported_cdt_node(exported_cdt_graph)
    node_data[f"{slot}_python_code"] = {
        "code": IMPORTED_CODE,
        "entrypoint": "main",
        "libraries": "",
        "global_kwargs": {},
    }
    node_data[f"{slot}_python_code_id"] = victim_python_code.id

    new_node = _imported_cdt_node(import_service, exported_cdt_graph)

    new_python_code = getattr(new_node, f"{slot}_python_code")
    assert new_python_code is not None
    assert new_python_code.id != victim_python_code.id
    assert new_python_code.code == IMPORTED_CODE
    _assert_victim_untouched(victim_python_code)


@pytest.mark.django_db
def test_round_trip_creates_fresh_pre_and_post_python_code(
    default_org, export_service, import_service
):
    source_pre_code = PythonCode.objects.create(
        code="def main(x):\n    return x", entrypoint="main", libraries="requests"
    )
    source_post_code = PythonCode.objects.create(
        code="def run():\n    return 1",
        entrypoint="run",
        libraries="",
        global_kwargs={"limit": 3},
    )
    graph = Graph.objects.create(name="cdt-python-code-round-trip", org=default_org)
    ClassificationDecisionTableNode.objects.create(
        graph=graph,
        node_name="cdt",
        pre_python_code=source_pre_code,
        post_python_code=source_post_code,
    )
    export_data = json.loads(
        json.dumps(export_service.export_entities(EntityType.GRAPH, [graph.id]))
    )

    new_node = _imported_cdt_node(import_service, export_data)

    for source_code, new_code in (
        (source_pre_code, new_node.pre_python_code),
        (source_post_code, new_node.post_python_code),
    ):
        assert new_code is not None
        assert new_code.id != source_code.id
        assert new_code.code == source_code.code
        assert new_code.entrypoint == source_code.entrypoint
        assert new_code.libraries == source_code.libraries
        assert new_code.global_kwargs == source_code.global_kwargs


@pytest.mark.django_db
def test_import_serializer_does_not_accept_python_code_ids(default_org, victim_python_code):
    graph = Graph.objects.create(name="cdt-serializer", org=default_org)

    serializer = ClassificationDecisionTableNodeImportSerializer(
        data={
            "graph": graph.id,
            "node_name": "cdt",
            "pre_python_code_id": victim_python_code.id,
            "post_python_code_id": victim_python_code.id,
        }
    )
    serializer.is_valid(raise_exception=True)
    node = serializer.save()

    assert node.pre_python_code_id is None
    assert node.post_python_code_id is None
    _assert_victim_untouched(victim_python_code)
