"""`use_storage` on a webhook trigger node: saved through the bulk-save API,
returned by GET, and kept by copy, export/import and version restore."""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.graph_versioning.services import GraphVersioningService
from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.schemas import ImportSettings
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.import_service import ImportService
from tables.models import Graph, PythonCode
from tables.models.graph_models import WebhookTriggerNode
from tables.services.copy_services.graph_copy_service import GraphCopyService
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

PYTHON_CODE_DATA = {"code": "def main(**kwargs): ...", "entrypoint": "main", "libraries": []}


@pytest.fixture
def acme_graph(acme):
    return Graph.objects.create(name="webhook-use-storage-flow", org=acme)


@pytest.fixture
def acme_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def storage_webhook_node(acme_graph):
    return WebhookTriggerNode.objects.create(
        graph=acme_graph,
        node_name="Hook",
        python_code=PythonCode.objects.create(code="def main(**kwargs): ..."),
        use_storage=True,
    )


def _bulk_save(client, graph: Graph, entry: dict):
    graph.refresh_from_db()
    return client.post(
        reverse("graphs-save-flow", args=[graph.id]),
        {"save_version": graph.save_version, "webhook_trigger_node_list": [entry]},
        format="json",
    )


def _export_and_import(graph: Graph, org_id: int) -> Graph:
    export_data = ExportService(entity_registry).export_entities(EntityType.GRAPH, [graph.id])
    id_mapper, _ = ImportService(entity_registry).import_data(
        export_data, EntityType.GRAPH, settings=ImportSettings(), org_id=org_id
    )
    return Graph.objects.get(pk=id_mapper.get_created_ids(EntityType.GRAPH)[0])


@pytest.mark.django_db
class TestBulkSave:
    def test_new_node_with_storage_is_saved_and_returned(self, acme_client, acme_graph):
        entry = {
            "graph": acme_graph.id,
            "node_name": "Hook",
            "metadata": {},
            "python_code": PYTHON_CODE_DATA,
            "use_storage": True,
        }

        save_response = _bulk_save(acme_client, acme_graph, entry)

        assert save_response.status_code == status.HTTP_200_OK, save_response.content
        assert WebhookTriggerNode.objects.get(graph=acme_graph).use_storage is True
        graph_response = acme_client.get(reverse("graphs-detail", args=[acme_graph.id]))
        assert graph_response.status_code == status.HTTP_200_OK, graph_response.content
        assert [node["use_storage"] for node in graph_response.data["webhook_trigger_node_list"]] == [
            True
        ]

    def test_new_node_without_the_field_defaults_to_no_storage(self, acme_client, acme_graph):
        entry = {
            "graph": acme_graph.id,
            "node_name": "Hook",
            "metadata": {},
            "python_code": PYTHON_CODE_DATA,
        }

        response = _bulk_save(acme_client, acme_graph, entry)

        assert response.status_code == status.HTTP_200_OK, response.content
        assert WebhookTriggerNode.objects.get(graph=acme_graph).use_storage is False

    def test_existing_node_can_turn_storage_off(
        self, acme_client, acme_graph, storage_webhook_node
    ):
        entry = {
            "id": storage_webhook_node.id,
            "graph": acme_graph.id,
            "node_name": storage_webhook_node.node_name,
            "metadata": {},
            "python_code": PYTHON_CODE_DATA,
            "use_storage": False,
        }

        response = _bulk_save(acme_client, acme_graph, entry)

        assert response.status_code == status.HTTP_200_OK, response.content
        storage_webhook_node.refresh_from_db()
        assert storage_webhook_node.use_storage is False


@pytest.mark.django_db
class TestContentHash:
    def test_toggling_use_storage_changes_content_hash(self, storage_webhook_node):
        hash_before = storage_webhook_node.content_hash

        storage_webhook_node.use_storage = False
        storage_webhook_node.save()

        assert storage_webhook_node.content_hash != hash_before


@pytest.mark.django_db
class TestCopyExportVersioning:
    def test_copy_keeps_use_storage(self, storage_webhook_node):
        new_graph = GraphCopyService().copy(storage_webhook_node.graph, name="copied")

        assert new_graph.webhook_trigger_node_list.get().use_storage is True

    def test_export_then_import_keeps_use_storage(self, acme, storage_webhook_node):
        imported_graph = _export_and_import(storage_webhook_node.graph, acme.id)

        assert imported_graph.id != storage_webhook_node.graph_id
        assert imported_graph.webhook_trigger_node_list.get().use_storage is True

    def test_version_restore_brings_back_use_storage(self, admin_acme, storage_webhook_node):
        graph = storage_webhook_node.graph
        versioning = GraphVersioningService()
        version = versioning.save_version(graph=graph, name="with-storage")
        WebhookTriggerNode.objects.filter(pk=storage_webhook_node.pk).update(use_storage=False)
        graph.refresh_from_db()

        versioning.restore_version(
            version, expected_save_version=graph.save_version, user=admin_acme
        )

        assert graph.webhook_trigger_node_list.get().use_storage is True
