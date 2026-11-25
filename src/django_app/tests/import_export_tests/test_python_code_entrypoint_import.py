"""`entrypoint` of the PythonCode behind every flow node code slot and a python tool,
on import.

Invariant: an import file whose entrypoint is not a plain Python name (or is a keyword) is
rejected whole with nothing created. A blank entrypoint still imports as "main".
"""

import copy

import pytest
from rest_framework.exceptions import ValidationError

from rbac.models import Organization
from tables.import_export.enums import EntityType
from tables.models import Graph, PythonCode, PythonCodeTool
from tests.helpers import UNRESTRICTED_EXPORT_POLICY
from tests.python_code_slots import PYTHON_CODE_SLOT_IDS, PYTHON_CODE_SLOTS

INJECTED_ENTRYPOINT = '(lambda f, *_: f)(main, "filler", __import__("os").system("id"))'
INVALID_ENTRYPOINTS = [INJECTED_ENTRYPOINT, "obj.method", "main()", "class"]
INVALID_ENTRYPOINT_IDS = ["expression", "dotted", "call", "keyword"]


@pytest.fixture(params=PYTHON_CODE_SLOTS, ids=PYTHON_CODE_SLOT_IDS)
def slot(request):
    return request.param


@pytest.fixture
def export_data(default_org, slot, export_service):
    graph = Graph.objects.create(name="entrypoint-export", org=default_org)
    slot.create(graph, PythonCode.objects.create(code="def main(): return 1", entrypoint="main"))
    return export_service.export_entities(
        EntityType.GRAPH, [graph.id], policy=UNRESTRICTED_EXPORT_POLICY
    ).data


def _with_entrypoint(export_data: dict, slot, entrypoint: str) -> dict:
    tampered = copy.deepcopy(export_data)
    [node] = [
        node
        for node in tampered[EntityType.GRAPH][0]["nodes"]
        if node["node_type"] == slot.entity_type
    ]
    node[slot.code_field]["entrypoint"] = entrypoint
    return tampered


@pytest.mark.django_db
@pytest.mark.parametrize("entrypoint", INVALID_ENTRYPOINTS, ids=INVALID_ENTRYPOINT_IDS)
def test_graph_import_rejects_anything_but_a_function_name(
    import_service, export_data, slot, entrypoint
):
    tampered = _with_entrypoint(export_data, slot, entrypoint)
    graph_count_before = Graph.objects.count()
    python_code_count_before = PythonCode.objects.count()

    with pytest.raises(ValidationError, match="entrypoint"):
        import_service.import_data(tampered, EntityType.GRAPH)

    assert Graph.objects.count() == graph_count_before
    assert PythonCode.objects.count() == python_code_count_before


@pytest.mark.django_db
@pytest.mark.parametrize(("entrypoint", "stored"), [("handle_event", "handle_event"), ("", "main")])
def test_graph_import_stores_a_function_name_and_blank_as_main(
    import_service, export_data, slot, entrypoint, stored
):
    tampered = _with_entrypoint(export_data, slot, entrypoint)

    id_mapper, _ = import_service.import_data(tampered, EntityType.GRAPH)

    graph = Graph.objects.get(pk=id_mapper.get_created_ids(EntityType.GRAPH)[0])
    assert slot.python_code_of(slot.only_node_in(graph)).entrypoint == stored


@pytest.mark.django_db
def test_python_tool_import_rejects_an_expression_entrypoint(
    default_org, export_service, import_service
):
    tool = PythonCodeTool.objects.create(
        name="entrypoint-tool",
        description="tool",
        python_code=PythonCode.objects.create(code="def main(): return 1"),
        org=default_org,
    )
    export_data = copy.deepcopy(
        export_service.export_entities(
            EntityType.PYTHON_CODE_TOOL, [tool.id], policy=UNRESTRICTED_EXPORT_POLICY
        ).data
    )
    export_data[EntityType.PYTHON_CODE_TOOL][0]["python_code"]["entrypoint"] = INJECTED_ENTRYPOINT
    importer = Organization.objects.create(name="entrypoint-tool-importer")

    with pytest.raises(ValidationError, match="entrypoint"):
        import_service.import_data(export_data, EntityType.PYTHON_CODE_TOOL, org_id=importer.id)

    assert not PythonCodeTool.objects.filter(org=importer).exists()
