import pytest

from django.urls import reverse

from tables.models import Graph, LLMConfig, LLMModel
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

    def test_import_refuses_a_reasoning_effort_the_model_cannot_take(
        self, auth_client, exportable_graph_with_agent_node
    ):
        source_config = exportable_graph_with_agent_node.agent_node_list.get().agent_definition.llm_config
        reasoning_model, _ = LLMModel.objects.get_or_create(
            name="gpt-5-mini", llm_provider=source_config.model.llm_provider, org=None
        )
        LLMConfig.objects.filter(pk=source_config.pk).update(
            model=reasoning_model, reasoning_effort="low"
        )
        export_data = (
            ExportService(entity_registry)
            .export_entities(
                EntityType.GRAPH,
                [exportable_graph_with_agent_node.id],
                policy=UNRESTRICTED_EXPORT_POLICY,
            )
            .data
        )
        [config_entry] = export_data[EntityType.LLM_CONFIG]
        config_entry["reasoning_effort"] = "max"
        graph_count_before = Graph.objects.count()
        config_count_before = LLMConfig.objects.count()

        response = auth_client.post(
            reverse("graphs-import-entity"),
            {"file": data_to_json_file(data=export_data, filename="effort.json")},
            format="multipart",
        )

        reason = (
            "Model 'gpt-5-mini' does not support reasoning effort 'max'. "
            "Supported: minimal, low, medium, high."
        )
        assert response.status_code == 400, response.data
        assert response.data["code"] == "unsupported_reasoning_effort"
        assert response.data["errors"] == [
            {"field": "reasoning_effort", "value": "max", "reason": reason}
        ]
        assert Graph.objects.count() == graph_count_before
        assert LLMConfig.objects.count() == config_count_before
