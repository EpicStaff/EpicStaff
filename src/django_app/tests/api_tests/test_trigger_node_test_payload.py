"""`test_payload` on webhook and Telegram trigger nodes: persisted, validated, copied,
exported and versioned like the node's other fields, and kept out of the content hash."""

import copy

import pytest
from django.urls import reverse
from rest_framework import status

from rbac.models import OrganizationUser
from tables.graph_versioning.services import GraphVersioningService
from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.schemas import ImportSettings
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.import_service import ImportService
from tables.models import Graph, PythonCode
from tables.models.graph_models import (
    TelegramTriggerNode,
    TelegramTriggerNodeField,
    WebhookTriggerNode,
)
from tables.services.copy_services.graph_copy_service import GraphCopyService
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

WEBHOOK_TEST_PAYLOAD = {"order_id": 42, "nested": {"items": [1, 2]}}
TELEGRAM_TEST_PAYLOAD = {"message": {"text": "hello"}}
PYTHON_CODE_DATA = {"code": "def main(**kwargs): ...", "entrypoint": "main", "libraries": []}

NODE_LISTS = {
    "webhook": "webhook_trigger_node_list",
    "telegram": "telegram_trigger_node_list",
}


@pytest.fixture
def acme_graph(acme):
    return Graph.objects.create(name="test-payload-flow", org=acme)


@pytest.fixture
def acme_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def webhook_node(acme_graph):
    return WebhookTriggerNode.objects.create(
        graph=acme_graph,
        node_name="Hook",
        python_code=PythonCode.objects.create(code="def main(**kwargs): ..."),
        test_payload=WEBHOOK_TEST_PAYLOAD,
    )


@pytest.fixture
def telegram_node(acme_graph, mock_telegram_service):
    node = TelegramTriggerNode.objects.create(
        graph=acme_graph, node_name="Bot", test_payload=TELEGRAM_TEST_PAYLOAD
    )
    TelegramTriggerNodeField.objects.create(
        telegram_trigger_node=node,
        parent="message",
        field_name="text",
        variable_path="variables.text",
    )
    return node


def _new_node_entry(kind: str, graph: Graph, test_payload) -> dict:
    entry = {
        "graph": graph.id,
        "node_name": f"{kind}-node",
        "metadata": {},
        "test_payload": test_payload,
    }
    if kind == "webhook":
        entry["python_code"] = PYTHON_CODE_DATA
    else:
        entry["fields"] = []
    return entry


def _bulk_save(client, graph: Graph, kind: str, entry: dict):
    graph.refresh_from_db()
    return client.post(
        reverse("graphs-save-flow", args=[graph.id]),
        {"save_version": graph.save_version, NODE_LISTS[kind]: [entry]},
        format="json",
    )


def _node_errors(response, kind: str) -> dict:
    return response.data["errors"][NODE_LISTS[kind]][0]["errors"]


def _without_test_payload(data):
    if isinstance(data, dict):
        return {key: _without_test_payload(value) for key, value in data.items() if key != "test_payload"}
    if isinstance(data, list):
        return [_without_test_payload(item) for item in data]
    return data


def _export_and_import(graph: Graph, org_id: int, transform=lambda data: data) -> Graph:
    export_data = ExportService(entity_registry).export_entities(EntityType.GRAPH, [graph.id])
    id_mapper, _ = ImportService(entity_registry).import_data(
        transform(copy.deepcopy(export_data)),
        EntityType.GRAPH,
        settings=ImportSettings(),
        org_id=org_id,
    )
    return Graph.objects.get(pk=id_mapper.get_created_ids(EntityType.GRAPH)[0])


@pytest.mark.django_db
class TestBulkSaveRoundTrip:
    @pytest.mark.parametrize("kind", ["webhook", "telegram"])
    def test_bulk_save_then_get_graph_returns_test_payload(
        self, acme_client, acme_graph, mock_telegram_service, kind
    ):
        payload = {"sample": kind, "values": [1, {"deep": None}]}

        save_response = _bulk_save(
            acme_client, acme_graph, kind, _new_node_entry(kind, acme_graph, payload)
        )

        assert save_response.status_code == status.HTTP_200_OK, save_response.content
        graph_response = acme_client.get(reverse("graphs-detail", args=[acme_graph.id]))
        assert graph_response.status_code == status.HTTP_200_OK, graph_response.content
        nodes = graph_response.data[NODE_LISTS[kind]]
        assert [node["test_payload"] for node in nodes] == [payload]

    @pytest.mark.parametrize("kind", ["webhook", "telegram"])
    def test_test_payload_defaults_to_empty_object(
        self, acme_client, acme_graph, mock_telegram_service, kind
    ):
        entry = _new_node_entry(kind, acme_graph, None)
        del entry["test_payload"]

        response = _bulk_save(acme_client, acme_graph, kind, entry)

        assert response.status_code == status.HTTP_200_OK, response.content
        model = WebhookTriggerNode if kind == "webhook" else TelegramTriggerNode
        assert model.objects.get(graph=acme_graph).test_payload == {}

    def test_bulk_save_updates_existing_node_test_payload(
        self, acme_client, acme_graph, telegram_node
    ):
        entry = {
            "id": telegram_node.id,
            "graph": acme_graph.id,
            "node_name": telegram_node.node_name,
            "fields": [{"parent": "message", "field_name": "text", "variable_path": "variables.text"}],
            "test_payload": {"message": {"text": "changed"}},
        }

        response = _bulk_save(acme_client, acme_graph, "telegram", entry)

        assert response.status_code == status.HTTP_200_OK, response.content
        telegram_node.refresh_from_db()
        assert telegram_node.test_payload == {"message": {"text": "changed"}}

    @pytest.mark.parametrize("kind", ["webhook", "telegram"])
    @pytest.mark.parametrize("test_payload", [[1], "text", None], ids=["list", "string", "null"])
    def test_non_object_test_payload_is_400(
        self, acme_client, acme_graph, mock_telegram_service, kind, test_payload
    ):
        response = _bulk_save(
            acme_client, acme_graph, kind, _new_node_entry(kind, acme_graph, test_payload)
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert set(_node_errors(response, kind)) == {"test_payload"}

    @pytest.mark.parametrize("kind", ["webhook", "telegram"])
    def test_oversized_test_payload_is_400(
        self, acme_client, acme_graph, mock_telegram_service, monkeypatch, kind
    ):
        monkeypatch.setattr(
            "tables.validators.trigger_payload_validator.MAX_TRIGGER_PAYLOAD_BYTES", 16
        )

        response = _bulk_save(
            acme_client,
            acme_graph,
            kind,
            _new_node_entry(kind, acme_graph, {"text": "longer than sixteen bytes"}),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert _node_errors(response, kind) == {
            "test_payload": ["Test payload must not exceed 16 bytes of compact JSON (got 36)."]
        }

    @pytest.mark.parametrize("kind", ["webhook", "telegram"])
    @pytest.mark.parametrize(
        "test_payload",
        [{"text": "a\x00b"}, {"nested": {"key\x00": 1}}],
        ids=["value", "nested-key"],
    )
    def test_nul_character_in_test_payload_is_400(
        self, acme_client, acme_graph, mock_telegram_service, kind, test_payload
    ):
        response = _bulk_save(
            acme_client, acme_graph, kind, _new_node_entry(kind, acme_graph, test_payload)
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert set(_node_errors(response, kind)) == {"test_payload"}
        assert "NUL character" in str(_node_errors(response, kind)["test_payload"])
        model = WebhookTriggerNode if kind == "webhook" else TelegramTriggerNode
        assert not model.objects.filter(graph=acme_graph).exists()

    def test_viewer_cannot_bulk_save(
        self, client_as, django_user_model, acme, role_viewer, acme_graph
    ):
        viewer = django_user_model.objects.create_user(
            email="viewer-test-payload@example.com", password="StrongPass123!"
        )
        OrganizationUser.objects.create(user=viewer, org=acme, role=role_viewer)
        client = client_as(viewer)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

        response = _bulk_save(
            client, acme_graph, "webhook", _new_node_entry("webhook", acme_graph, {"a": 1})
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert not WebhookTriggerNode.objects.filter(graph=acme_graph).exists()


@pytest.mark.django_db
class TestContentHash:
    @pytest.mark.parametrize("node_fixture", ["webhook_node", "telegram_node"])
    def test_editing_test_payload_keeps_content_hash(self, request, node_fixture):
        node = request.getfixturevalue(node_fixture)
        hash_before = node.content_hash

        node.test_payload = {"completely": "different"}
        node.save()
        node.refresh_from_db()

        assert node.content_hash == hash_before

    def test_editing_another_field_still_changes_content_hash(self, webhook_node):
        hash_before = webhook_node.content_hash

        webhook_node.node_name = "Renamed"
        webhook_node.save()

        assert webhook_node.content_hash != hash_before


@pytest.mark.django_db
class TestCopyExportVersioning:
    def test_copy_keeps_test_payload(self, webhook_node, telegram_node):
        new_graph = GraphCopyService().copy(webhook_node.graph, name="copied")

        assert new_graph.webhook_trigger_node_list.get().test_payload == WEBHOOK_TEST_PAYLOAD
        assert new_graph.telegram_trigger_node_list.get().test_payload == TELEGRAM_TEST_PAYLOAD

    def test_export_then_import_keeps_test_payload(self, acme, webhook_node, telegram_node):
        imported_graph = _export_and_import(webhook_node.graph, acme.id)

        assert imported_graph.id != webhook_node.graph_id
        assert imported_graph.webhook_trigger_node_list.get().test_payload == WEBHOOK_TEST_PAYLOAD
        assert imported_graph.telegram_trigger_node_list.get().test_payload == TELEGRAM_TEST_PAYLOAD

    def test_export_without_test_payload_imports_as_empty_object(
        self, acme, webhook_node, telegram_node
    ):
        imported_graph = _export_and_import(
            webhook_node.graph, acme.id, transform=_without_test_payload
        )

        assert imported_graph.webhook_trigger_node_list.get().test_payload == {}
        assert imported_graph.telegram_trigger_node_list.get().test_payload == {}

    def test_version_restore_brings_back_test_payload(
        self, admin_acme, webhook_node, telegram_node
    ):
        graph = webhook_node.graph
        versioning = GraphVersioningService()
        version = versioning.save_version(graph=graph, name="with-test-payloads")
        WebhookTriggerNode.objects.filter(pk=webhook_node.pk).update(test_payload={})
        TelegramTriggerNode.objects.filter(pk=telegram_node.pk).update(test_payload={})
        graph.refresh_from_db()

        versioning.restore_version(
            version, expected_save_version=graph.save_version, user=admin_acme
        )

        assert graph.webhook_trigger_node_list.get().test_payload == WEBHOOK_TEST_PAYLOAD
        assert graph.telegram_trigger_node_list.get().test_payload == TELEGRAM_TEST_PAYLOAD
