"""The import boundary applies the same `test_payload` rule as the node API.

`test_payload` is written straight into a `jsonb` column, so a crafted export
file must not be able to skip the size cap, the NUL check or the JSON-object
check that `validate_trigger_payload` enforces on the trigger node endpoints.
"""

import copy

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.exceptions import ValidationError

from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.import_export.strategies.nodes.telegram_trigger_node import (
    TelegramTriggerNodeStrategy,
)
from tables.import_export.strategies.nodes.webhook_trigger_node import (
    WebhookTriggerNodeStrategy,
)
from tables.models import Graph, PythonCode, TelegramTriggerNode, WebhookTriggerNode
from tests.helpers import data_to_json_file

VALID_TEST_PAYLOAD = {"order_id": 42, "text": "привіт 🙂", "items": [{"sku": "A-1"}]}
NUL_PAYLOADS = [{"text": "a\x00b"}, {"nested": {"key\x00": 1}}, {"items": [{"deep": "\x00"}]}]
NON_OBJECT_PAYLOADS = [[1, 2], "text", 7]
TRIGGER_NODE_TYPES = [EntityType.WEBHOOK_TRIGGER_NODE, EntityType.TELEGRAM_TRIGGER_NODE]


@pytest.fixture
def source_graph(default_org, mock_telegram_service):
    graph = Graph.objects.create(name="test-payload-import-flow", org=default_org)
    WebhookTriggerNode.objects.create(
        graph=graph,
        node_name="Incoming order",
        python_code=PythonCode.objects.create(code="def main(trigger_payload, **kwargs): ..."),
        test_payload=VALID_TEST_PAYLOAD,
    )
    TelegramTriggerNode.objects.create(
        graph=graph, node_name="Bot message", test_payload=VALID_TEST_PAYLOAD
    )
    return graph


@pytest.fixture
def export_data(source_graph):
    return ExportService(entity_registry).export_entities(EntityType.GRAPH, [source_graph.id])


def _exported_nodes(export_data, node_type):
    return [
        node for node in export_data[EntityType.GRAPH][0]["nodes"] if node["node_type"] == node_type
    ]


def _with_test_payload(export_data, node_type, test_payload):
    tampered = copy.deepcopy(export_data)
    for node in _exported_nodes(tampered, node_type):
        node["test_payload"] = test_payload
    return tampered


def _imported_graph(import_service, export_data):
    id_mapper, _ = import_service.import_data(copy.deepcopy(export_data), EntityType.GRAPH)
    return Graph.objects.get(pk=id_mapper.get_created_ids(EntityType.GRAPH)[0])


def _strategy_input(strategy, graph):
    """Node data as `GraphStrategy._create_nodes` hands it to a node strategy."""
    data = {"node_name": "imported", "graph": graph.id}
    if isinstance(strategy, WebhookTriggerNodeStrategy):
        data["python_code"] = {
            "code": "def main(**kwargs): ...",
            "entrypoint": "main",
            "libraries": "",
        }
    return data


def _id_mapper_for(graph):
    id_mapper = IDMapper()
    id_mapper.map(EntityType.GRAPH, graph.id, graph.id, was_created=False)
    return id_mapper


@pytest.mark.django_db
class TestTriggerNodeTestPayloadImportStrategies:
    @pytest.fixture(params=["webhook", "telegram"])
    def strategy(self, request):
        if request.param == "webhook":
            return WebhookTriggerNodeStrategy()
        return TelegramTriggerNodeStrategy()

    @pytest.fixture
    def target_graph(self, default_org, mock_telegram_service):
        return Graph.objects.create(name="target-flow", org=default_org)

    def test_oversize_payload_is_rejected(self, strategy, target_graph, monkeypatch):
        monkeypatch.setattr(
            "tables.validators.trigger_payload_validator.MAX_TRIGGER_PAYLOAD_BYTES", 16
        )
        data = {
            **_strategy_input(strategy, target_graph),
            "test_payload": {"text": "longer than sixteen bytes"},
        }

        with pytest.raises(ValidationError) as exc_info:
            strategy.create_entity(data, _id_mapper_for(target_graph))

        assert exc_info.value.detail["test_payload"] == [
            "Test payload must not exceed 16 bytes of compact JSON (got 36)."
        ]

    @pytest.mark.parametrize("test_payload", NUL_PAYLOADS, ids=["value", "nested-key", "in-list"])
    def test_nul_character_is_rejected(self, strategy, target_graph, test_payload):
        data = {**_strategy_input(strategy, target_graph), "test_payload": test_payload}

        with pytest.raises(ValidationError) as exc_info:
            strategy.create_entity(data, _id_mapper_for(target_graph))

        assert "NUL character" in str(exc_info.value.detail["test_payload"][0])

    @pytest.mark.parametrize("test_payload", NON_OBJECT_PAYLOADS, ids=["list", "string", "number"])
    def test_non_object_payload_is_rejected(self, strategy, target_graph, test_payload):
        data = {**_strategy_input(strategy, target_graph), "test_payload": test_payload}

        with pytest.raises(ValidationError) as exc_info:
            strategy.create_entity(data, _id_mapper_for(target_graph))

        assert exc_info.value.detail["test_payload"] == ["Test payload must be a JSON object."]

    def test_missing_payload_defaults_to_empty_object(self, strategy, target_graph):
        node = strategy.create_entity(
            _strategy_input(strategy, target_graph), _id_mapper_for(target_graph)
        )

        node.refresh_from_db()
        assert node.test_payload == {}


@pytest.mark.django_db
class TestTriggerNodeTestPayloadGraphImport:
    def test_valid_payload_round_trips(self, import_service, export_data):
        for node_type in TRIGGER_NODE_TYPES:
            assert _exported_nodes(export_data, node_type)[0]["test_payload"] == VALID_TEST_PAYLOAD

        imported_graph = _imported_graph(import_service, export_data)

        assert imported_graph.webhook_trigger_node_list.get().test_payload == VALID_TEST_PAYLOAD
        assert imported_graph.telegram_trigger_node_list.get().test_payload == VALID_TEST_PAYLOAD

    def test_export_without_the_field_imports_as_empty_object(self, import_service, export_data):
        legacy_export = copy.deepcopy(export_data)
        for node_type in TRIGGER_NODE_TYPES:
            for node in _exported_nodes(legacy_export, node_type):
                del node["test_payload"]

        imported_graph = _imported_graph(import_service, legacy_export)

        assert imported_graph.webhook_trigger_node_list.get().test_payload == {}
        assert imported_graph.telegram_trigger_node_list.get().test_payload == {}

    @pytest.mark.parametrize("node_type", TRIGGER_NODE_TYPES)
    def test_invalid_payload_rolls_back_the_whole_import(
        self, import_service, export_data, node_type
    ):
        tampered = _with_test_payload(export_data, node_type, {"text": "a\x00b"})
        graph_count_before = Graph.objects.count()

        with pytest.raises(ValidationError) as exc_info:
            import_service.import_data(tampered, EntityType.GRAPH)

        assert "test_payload" in exc_info.value.detail
        assert Graph.objects.count() == graph_count_before


@pytest.mark.django_db
class TestTriggerNodeTestPayloadImportEndpoint:
    @pytest.mark.parametrize("node_type", TRIGGER_NODE_TYPES)
    def test_non_object_payload_is_a_400_not_a_server_error(
        self, auth_client, export_data, node_type
    ):
        tampered = _with_test_payload(export_data, node_type, [1, 2])
        graph_count_before = Graph.objects.count()

        response = auth_client.post(
            reverse("graphs-import-entity"),
            {"file": data_to_json_file(data=tampered, filename="tampered.json")},
            format="multipart",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert response.data["message"] == "test_payload: Test payload must be a JSON object."
        assert Graph.objects.count() == graph_count_before
