"""`execution_timeout` on the five code-running nodes survives a graph export and
import, under the same rules as the node API.

Invariant: an export carries each node's execution timeout and an import restores
it. A file is untrusted input from any deployment, so the import applies the API's
rule: a file without the field (exported before nodes had a timeout) gets this
deployment's ceiling, a value above the ceiling is saved as the ceiling, and a value
below 1, null or not a whole number rejects the whole import with nothing created.
"""

import copy

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.exceptions import ValidationError

from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.models import Graph
from tests.execution_timeout_node_specs import (
    EXECUTION_TIMEOUT_NODE_SPEC_IDS,
    EXECUTION_TIMEOUT_NODE_SPECS,
    INVALID_EXECUTION_TIMEOUT_IDS,
    INVALID_EXECUTION_TIMEOUTS,
)
from tests.helpers import data_to_json_file

CEILING_MINUTES = 7
STORED_MINUTES = 4


@pytest.fixture(autouse=True)
def sandbox_ceiling(settings):
    settings.SANDBOX_MAX_EXECUTION_TIMEOUT_MINUTES = CEILING_MINUTES


@pytest.fixture(params=EXECUTION_TIMEOUT_NODE_SPECS, ids=EXECUTION_TIMEOUT_NODE_SPEC_IDS)
def spec(request):
    return request.param


@pytest.fixture
def source_graph(default_org, spec):
    graph = Graph.objects.create(name="execution-timeout-export", org=default_org)
    spec.create(graph, execution_timeout=STORED_MINUTES)
    return graph


@pytest.fixture
def export_data(source_graph):
    return ExportService(entity_registry).export_entities(EntityType.GRAPH, [source_graph.id])


def _exported_node(export_data, spec) -> dict:
    [node] = [
        node
        for node in export_data[EntityType.GRAPH][0]["nodes"]
        if node["node_type"] == spec.entity_type
    ]
    return node


def _with_execution_timeout(export_data, spec, execution_timeout) -> dict:
    tampered = copy.deepcopy(export_data)
    _exported_node(tampered, spec)["execution_timeout"] = execution_timeout
    return tampered


def _without_execution_timeout(export_data, spec) -> dict:
    legacy = copy.deepcopy(export_data)
    del _exported_node(legacy, spec)["execution_timeout"]
    return legacy


def _imported_execution_timeout(import_service, export_data, spec) -> int:
    id_mapper, _ = import_service.import_data(copy.deepcopy(export_data), EntityType.GRAPH)
    graph = Graph.objects.get(pk=id_mapper.get_created_ids(EntityType.GRAPH)[0])
    return getattr(graph, spec.graph_list_key).get().execution_timeout


@pytest.mark.django_db
class TestGraphExportImport:
    def test_export_carries_the_execution_timeout(self, export_data, spec):
        assert _exported_node(export_data, spec)["execution_timeout"] == STORED_MINUTES

    def test_import_restores_the_execution_timeout(self, import_service, export_data, spec):
        assert _imported_execution_timeout(import_service, export_data, spec) == STORED_MINUTES

    def test_file_without_the_field_imports_with_the_ceiling(
        self, import_service, export_data, spec
    ):
        legacy = _without_execution_timeout(export_data, spec)

        assert _imported_execution_timeout(import_service, legacy, spec) == CEILING_MINUTES

    def test_value_above_the_ceiling_imports_as_the_ceiling(
        self, import_service, export_data, spec
    ):
        tampered = _with_execution_timeout(export_data, spec, CEILING_MINUTES * 100)

        assert _imported_execution_timeout(import_service, tampered, spec) == CEILING_MINUTES

    @pytest.mark.parametrize(
        "invalid", INVALID_EXECUTION_TIMEOUTS, ids=INVALID_EXECUTION_TIMEOUT_IDS
    )
    def test_invalid_value_rolls_back_the_whole_import(
        self, import_service, export_data, spec, invalid
    ):
        tampered = _with_execution_timeout(export_data, spec, invalid)
        graph_count_before = Graph.objects.count()
        node_count_before = spec.model.objects.count()

        with pytest.raises(ValidationError) as exc_info:
            import_service.import_data(tampered, EntityType.GRAPH)

        assert "execution_timeout" in exc_info.value.detail
        assert Graph.objects.count() == graph_count_before
        assert spec.model.objects.count() == node_count_before


@pytest.mark.django_db
def test_import_endpoint_answers_an_invalid_value_with_400(auth_client, export_data, spec):
    tampered = _with_execution_timeout(export_data, spec, 0)
    graph_count_before = Graph.objects.count()

    response = auth_client.post(
        reverse("graphs-import-entity"),
        {"file": data_to_json_file(data=tampered, filename="tampered.json")},
        format="multipart",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert "execution_timeout" in response.data["message"]
    assert Graph.objects.count() == graph_count_before


@pytest.mark.django_db
def test_export_of_a_row_stored_above_the_ceiling_carries_the_ceiling(source_graph, spec):
    spec.model._base_manager.filter(graph=source_graph).update(
        execution_timeout=CEILING_MINUTES + 20
    )

    export_data = ExportService(entity_registry).export_entities(
        EntityType.GRAPH, [source_graph.id]
    )

    assert _exported_node(export_data, spec)["execution_timeout"] == CEILING_MINUTES
