"""`execution_timeout` of the PythonCode behind every flow node code slot survives a graph
export and import.

Invariant: an export carries each PythonCode's execution timeout and an import restores
it. An import file can come from a deployment or release with other limits, so the import
moves a value outside this deployment's range to the nearest limit rather than failing: a
value above the maximum is saved as the maximum and one below the minimum as the minimum. A
file without the field (exported before PythonCode had a timeout) gets this deployment's
default. A value that is not a non-negative integer rejects the whole import with nothing
created.
"""

import copy

import pytest
from rest_framework.exceptions import ValidationError

from rbac.models import Organization
from tables.import_export.enums import EntityType
from tables.models import Graph, PythonCode, PythonCodeTool
from tests.python_code_slots import PYTHON_CODE_SLOT_IDS, PYTHON_CODE_SLOTS

MIN_SECONDS = 3
MAX_SECONDS = 600
DEFAULT_SECONDS = 45
STORED_SECONDS = 120


@pytest.fixture(autouse=True)
def execution_timeout_limits(settings):
    settings.MAX_EXECUTION_TIMEOUT_SECONDS = MAX_SECONDS
    settings.DEFAULT_EXECUTION_TIMEOUT_SECONDS = DEFAULT_SECONDS


@pytest.fixture(params=PYTHON_CODE_SLOTS, ids=PYTHON_CODE_SLOT_IDS)
def slot(request):
    return request.param


@pytest.fixture
def export_data(default_org, slot, export_service):
    graph = Graph.objects.create(name="execution-timeout-export", org=default_org)
    slot.create(
        graph,
        PythonCode.objects.create(code="def main(): return 1", execution_timeout=STORED_SECONDS),
    )
    return export_service.export_entities(EntityType.GRAPH, [graph.id])


def _exported_python_code(export_data: dict, slot) -> dict:
    [node] = [
        node
        for node in export_data[EntityType.GRAPH][0]["nodes"]
        if node["node_type"] == slot.entity_type
    ]
    return node[slot.code_field]


def _with_execution_timeout(export_data: dict, slot, execution_timeout) -> dict:
    tampered = copy.deepcopy(export_data)
    _exported_python_code(tampered, slot)["execution_timeout"] = execution_timeout
    return tampered


def _imported_execution_timeout(import_service, export_data: dict, slot) -> int:
    id_mapper, _ = import_service.import_data(copy.deepcopy(export_data), EntityType.GRAPH)
    graph = Graph.objects.get(pk=id_mapper.get_created_ids(EntityType.GRAPH)[0])
    return slot.python_code_of(slot.only_node_in(graph)).execution_timeout


@pytest.mark.django_db
def test_export_carries_the_execution_timeout(export_data, slot):
    assert _exported_python_code(export_data, slot)["execution_timeout"] == STORED_SECONDS


@pytest.mark.django_db
def test_import_restores_the_execution_timeout(import_service, export_data, slot):
    assert _imported_execution_timeout(import_service, export_data, slot) == STORED_SECONDS


@pytest.mark.django_db
def test_file_without_the_field_imports_with_the_default(import_service, export_data, slot):
    legacy = copy.deepcopy(export_data)
    del _exported_python_code(legacy, slot)["execution_timeout"]

    assert _imported_execution_timeout(import_service, legacy, slot) == DEFAULT_SECONDS


@pytest.mark.django_db
def test_value_above_the_maximum_imports_as_the_maximum(import_service, export_data, slot):
    tampered = _with_execution_timeout(export_data, slot, MAX_SECONDS * 100)

    assert _imported_execution_timeout(import_service, tampered, slot) == MAX_SECONDS


@pytest.mark.django_db
@pytest.mark.parametrize("below_minimum", [2, 0], ids=["below-minimum", "zero"])
def test_value_below_the_minimum_imports_as_the_minimum(
    import_service, export_data, slot, below_minimum
):
    tampered = _with_execution_timeout(export_data, slot, below_minimum)

    assert _imported_execution_timeout(import_service, tampered, slot) == MIN_SECONDS


@pytest.mark.django_db
@pytest.mark.parametrize("invalid", [-1, None, "ten"], ids=["negative", "null", "text"])
def test_invalid_value_rolls_back_the_whole_import(import_service, export_data, slot, invalid):
    tampered = _with_execution_timeout(export_data, slot, invalid)
    graph_count_before = Graph.objects.count()
    python_code_count_before = PythonCode.objects.count()

    with pytest.raises(ValidationError, match="execution_timeout"):
        import_service.import_data(tampered, EntityType.GRAPH)

    assert Graph.objects.count() == graph_count_before
    assert PythonCode.objects.count() == python_code_count_before


@pytest.mark.django_db
def test_python_tool_round_trip_keeps_the_execution_timeout(
    default_org, export_service, import_service
):
    tool = PythonCodeTool.objects.create(
        name="execution-timeout-tool",
        description="tool",
        python_code=PythonCode.objects.create(
            code="def main(): return 1", execution_timeout=STORED_SECONDS
        ),
        org=default_org,
    )
    export_data = export_service.export_entities(EntityType.PYTHON_CODE_TOOL, [tool.id])
    [exported_tool] = export_data[EntityType.PYTHON_CODE_TOOL]
    assert exported_tool["python_code"]["execution_timeout"] == STORED_SECONDS
    other_org = Organization.objects.create(name="execution-timeout-tool-importer")

    id_mapper, _ = import_service.import_data(
        export_data, EntityType.PYTHON_CODE_TOOL, org_id=other_org.id
    )

    [imported_id] = id_mapper.get_created_ids(EntityType.PYTHON_CODE_TOOL)
    imported_tool = PythonCodeTool.objects.select_related("python_code").get(pk=imported_id)
    assert imported_tool.org_id == other_org.id
    assert imported_tool.python_code.execution_timeout == STORED_SECONDS


@pytest.mark.django_db
def test_python_tool_below_the_minimum_imports_as_the_minimum(
    default_org, export_service, import_service
):
    tool = PythonCodeTool.objects.create(
        name="execution-timeout-tool-below-minimum",
        description="tool",
        python_code=PythonCode.objects.create(
            code="def main(): return 1", execution_timeout=STORED_SECONDS
        ),
        org=default_org,
    )
    export_data = export_service.export_entities(EntityType.PYTHON_CODE_TOOL, [tool.id])
    export_data[EntityType.PYTHON_CODE_TOOL][0]["python_code"]["execution_timeout"] = 2
    other_org = Organization.objects.create(name="execution-timeout-tool-below-minimum-importer")

    id_mapper, _ = import_service.import_data(
        export_data, EntityType.PYTHON_CODE_TOOL, org_id=other_org.id
    )

    [imported_id] = id_mapper.get_created_ids(EntityType.PYTHON_CODE_TOOL)
    imported_tool = PythonCodeTool.objects.select_related("python_code").get(pk=imported_id)
    assert imported_tool.python_code.execution_timeout == MIN_SECONDS
