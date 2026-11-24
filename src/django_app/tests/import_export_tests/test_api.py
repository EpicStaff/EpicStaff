import pytest

from django.urls import reverse

from tables.models import Graph
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
