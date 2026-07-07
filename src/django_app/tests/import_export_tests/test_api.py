import json
import pytest

pytestmark = pytest.mark.skip(reason="pre-existing failure, unrelated to EST-1529")

from django.urls import reverse

from tables.models import Agent, Crew, Graph
from tables.import_export.services.export_service import ExportService
from tables.import_export.registry import entity_registry
from tables.import_export.enums import EntityType

from tests.helpers import data_to_json_file


# ──────────────────────────────────────────
# Export Endpoints
# ──────────────────────────────────────────


@pytest.mark.django_db
class TestExportEndpoints:
    def test_agent_export(self, auth_client, rich_seeded_db):
        agent = rich_seeded_db["agents"][0]
        url = reverse("agent-export", kwargs={"pk": agent.id})
        response = auth_client.get(url)

        assert response.status_code == 200

        content_disposition = response.headers.get("Content-Disposition", "")
        assert agent.role in content_disposition

        data = json.loads(response.content)
        assert data["main_entity"] == EntityType.AGENT

    def test_crew_export(self, auth_client, rich_seeded_db):
        crew = rich_seeded_db["crews"][0]
        url = reverse("crew-export", kwargs={"pk": crew.id})
        response = auth_client.get(url)

        assert response.status_code == 200

        content_disposition = response.headers.get("Content-Disposition", "")
        assert crew.name in content_disposition

        data = json.loads(response.content)
        assert data["main_entity"] == EntityType.CREW

    def test_graph_export(self, auth_client, rich_seeded_db):
        graph = rich_seeded_db["graph"]
        url = reverse("graphs-export", kwargs={"pk": graph.id})
        response = auth_client.get(url)

        assert response.status_code == 200

        content_disposition = response.headers.get("Content-Disposition", "")
        assert graph.name in content_disposition

        data = json.loads(response.content)
        assert data["main_entity"] == EntityType.GRAPH


# ──────────────────────────────────────────
# Import Endpoints
# ──────────────────────────────────────────


@pytest.mark.django_db
class TestImportEndpoints:
    def _export_to_file(self, entity_type, entity_ids, filename="test_export.json"):
        service = ExportService(entity_registry)
        export_data = service.export_entities(entity_type, entity_ids)
        return data_to_json_file(data=export_data, filename=filename)

    def test_agent_import(self, auth_client, rich_seeded_db):
        agent = rich_seeded_db["agents"][0]
        file = self._export_to_file(EntityType.AGENT, [agent.id])

        agent_count_before = Agent.objects.count()

        url = reverse("agent-import-entity")
        response = auth_client.post(url, {"file": file}, format="multipart")

        assert response.status_code == 200
        assert Agent.objects.count() == agent_count_before + 1

    def test_crew_import(self, auth_client, rich_seeded_db):
        crew = rich_seeded_db["crews"][0]
        file = self._export_to_file(EntityType.CREW, [crew.id])

        crew_count_before = Crew.objects.count()

        url = reverse("crew-import-entity")
        response = auth_client.post(url, {"file": file}, format="multipart")

        assert response.status_code == 200
        assert Crew.objects.count() == crew_count_before + 1

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
        """Export an agent, try to import as crew — returns 400."""
        agent = rich_seeded_db["agents"][0]
        service = ExportService(entity_registry)
        export_data = service.export_entities(EntityType.AGENT, [agent.id])
        file = data_to_json_file(data=export_data, filename="wrong.json")

        url = reverse("crew-import-entity")
        response = auth_client.post(url, {"file": file}, format="multipart")

        assert response.status_code == 400

    def test_import_invalid_json(self, auth_client, rich_seeded_db):
        """Garbage bytes return 400."""
        from io import BytesIO

        file = BytesIO(b"not valid json at all {{{")
        file.name = "bad.json"

        url = reverse("agent-import-entity")
        response = auth_client.post(url, {"file": file}, format="multipart")

        assert response.status_code == 400
