import pytest

from django.urls import reverse

from ai_models.models import LLMConfig
from tables.models import Graph, PythonCode, PythonCodeTool, PythonNode
from tables.import_export.services.export_service import ExportService
from tables.import_export.registry import entity_registry
from tables.import_export.enums import EntityType

from tests.helpers import UNRESTRICTED_EXPORT_POLICY, data_to_json_file


# ──────────────────────────────────────────
# Import Endpoints
# ──────────────────────────────────────────


@pytest.mark.django_db
class TestImportEndpoints:
    def _export_to_file(self, entity_type, entity_ids, filename="test_export.json"):
        service = ExportService(entity_registry)
        export_data = service.export_entities(
            entity_type, entity_ids, policy=UNRESTRICTED_EXPORT_POLICY
        ).data
        return data_to_json_file(data=export_data, filename=filename)

    def test_graph_import(self, auth_client, rich_seeded_db):
        graph = rich_seeded_db["graph"]
        file = self._export_to_file(EntityType.GRAPH, [graph.id])

        graph_count_before = Graph.objects.count()

        url = reverse("graphs-import-entity")
        response = auth_client.post(url, {"file": file}, format="multipart")

        assert response.status_code == 200
        assert Graph.objects.count() == graph_count_before + 1


# ──────────────────────────────────────────
# Error Cases
# ──────────────────────────────────────────


@pytest.mark.django_db
class TestImportErrors:
    def test_import_wrong_entity_type(self, auth_client, rich_seeded_db):
        """A payload whose main_entity is not a flow is rejected with 400."""
        export_data = {"main_entity": EntityType.LABEL, EntityType.LABEL: []}
        file = data_to_json_file(data=export_data, filename="wrong.json")

        url = reverse("graphs-import-entity")
        response = auth_client.post(url, {"file": file}, format="multipart")

        assert response.status_code == 400

    def test_import_invalid_json(self, auth_client, rich_seeded_db):
        """Garbage bytes return 400."""
        from io import BytesIO

        file = BytesIO(b"not valid json at all {{{")
        file.name = "bad.json"

        url = reverse("graphs-import-entity")
        response = auth_client.post(url, {"file": file}, format="multipart")

        assert response.status_code == 400


def _python_nodes(export_data):
    [flow] = export_data[EntityType.GRAPH]
    return [node for node in flow["nodes"] if node["node_type"] == EntityType.PYTHON_NODE]


def _set_python_code(export_data, value):
    [python_node] = _python_nodes(export_data)
    python_node["python_code"] = value


# Each case crashed a version conversion before the file's shape was checked.
MALFORMED_FLOW_FILES = {
    "flow nodes not a list": (
        lambda data: data[EntityType.GRAPH][0].update(nodes="none"),
        "nodes must be a list of objects",
    ),
    "python_code not an object": (
        lambda data: _set_python_code(data, "def main(): pass"),
        "python_code must be an object or null",
    ),
    "tool entry not an object": (
        lambda data: data.update({EntityType.PYTHON_CODE_TOOL: [1]}),
        "PythonCodeTool must be a list of objects",
    ),
    "parameters not an object": (
        lambda data: data.update({EntityType.LLM_CONFIG: [{"id": 1, "parameters": [0.2]}]}),
        "LLMConfig 1: parameters must be an object or null",
    ),
}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("malform", "message"), MALFORMED_FLOW_FILES.values(), ids=MALFORMED_FLOW_FILES.keys()
)
def test_a_malformed_unversioned_flow_file_is_refused_and_writes_nothing(
    auth_client, rich_seeded_db, malform, message
):
    graph = rich_seeded_db["graph"]
    PythonNode.objects.create(
        graph=graph,
        node_name="fetch",
        python_code=PythonCode.objects.create(code="def main(): ...", entrypoint="main"),
    )
    export_data = ExportService(entity_registry).export_entities(
        EntityType.GRAPH, [graph.id], policy=UNRESTRICTED_EXPORT_POLICY
    ).data
    # A file without a version runs through every conversion.
    del export_data["version"]
    malform(export_data)
    counts_before = (Graph.objects.count(), LLMConfig.objects.count(), PythonCodeTool.objects.count())

    response = auth_client.post(
        reverse("graphs-import-entity"),
        {"file": data_to_json_file(data=export_data, filename="flow.json")},
        format="multipart",
    )

    assert response.status_code == 400, response.content
    assert message in response.json()["message"]
    counts_after = (Graph.objects.count(), LLMConfig.objects.count(), PythonCodeTool.objects.count())
    assert counts_after == counts_before
