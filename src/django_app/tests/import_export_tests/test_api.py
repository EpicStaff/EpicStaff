import json
import uuid
import pytest

from django.urls import reverse

from tables.models import Graph
from tables.import_export.services.export_service import ExportService
from tables.import_export.registry import entity_registry
from tables.import_export.enums import EntityType

from tests.helpers import data_to_json_file


# ──────────────────────────────────────────
# Export Endpoints
# ──────────────────────────────────────────


@pytest.mark.django_db
class TestExportEndpoints:
    def test_graph_export(self, auth_client, rich_seeded_db):
        graph = rich_seeded_db["graph"]
        url = reverse("graphs-export", kwargs={"pk": graph.id})
        response = auth_client.get(url)

        assert response.status_code == 200

        content_disposition = response.headers.get("Content-Disposition", "")
        assert graph.name in content_disposition

        data = json.loads(response.content)
        assert data["main_entity"] == EntityType.GRAPH

    def test_cdt_node_export_with_sections_returns_json_serializable_data(
        self, auth_client, default_org, cdt_condition_group_factory
    ):
        """Regression test for: `section` in `condition_groups` was serialized
        as a raw uuid.UUID object, causing "Object of type UUID is not JSON
        serializable" errors."""
        graph, *_ = cdt_condition_group_factory(default_org)

        url = reverse("graphs-export", kwargs={"pk": graph.id})
        response = auth_client.get(url)

        assert response.status_code == 200
        data = json.loads(response.content)
        assert json.dumps(data) is not None

    def test_cdt_node_section_field_is_string_or_null(
        self, auth_client, default_org, cdt_condition_group_factory
    ):
        graph, *_ = cdt_condition_group_factory(default_org)

        url = reverse("graphs-export", kwargs={"pk": graph.id})
        response = auth_client.get(url)

        assert response.status_code == 200
        data = json.loads(response.content)

        # The CDT node is nested inside the exported Flow entry's flat "nodes"
        # list, tagged with its node_type, not a separate top-level entity key.
        exported_flow = data[EntityType.GRAPH][0]
        exported_cdt = next(
            node
            for node in exported_flow["nodes"]
            if node["node_type"] == EntityType.CLASSIFICATION_DECISION_TABLE_NODE
        )
        section_value = exported_cdt["condition_groups"][0]["section"]

        assert isinstance(section_value, str)
        uuid.UUID(section_value)  # raises ValueError if not a valid UUID string


# ──────────────────────────────────────────
# Import Endpoints
# ──────────────────────────────────────────


@pytest.mark.django_db
class TestImportEndpoints:
    def _export_to_file(self, entity_type, entity_ids, filename="test_export.json"):
        service = ExportService(entity_registry)
        export_data = service.export_entities(entity_type, entity_ids)
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
