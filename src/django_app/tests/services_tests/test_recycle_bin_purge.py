"""PurgeService: a binned root goes for good, with what cascades from it."""

from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from rbac.models import Organization
from src.shared.enums.knowledge_new import RAGStrategy
from tables.clients.errors import ClientNotAvailableError, ClientResourceNotFoundError
from tables.exceptions import NotInRecycleBinError
from tables.models import (
    DocumentContent,
    DocumentMetadata,
    Graph,
    PythonCode,
    PythonCodeTool,
    SourceCollection,
    StorageFile,
    TaskNode,
)
from tables.models.knowledge_models import BaseRagType, GraphRag, GraphRagIndexConfig
from tables.services.recycle_bin.purge_service import PurgeService
from tables.services.soft_delete import DeleteService
from tables.services.storage_service.manager import StorageManager
from tables.services.storage_service.recycle_bin import StorageRecycleBinService
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend, seed_file

KNOWLEDGE_DELETE = "tables.clients.KnowledgeClient.delete"


def _collection_with_graph_rag(org):
    collection = SourceCollection.objects.create(org=org, collection_name="Graph docs")
    base_rag_type = BaseRagType.objects.create(rag_type=BaseRagType.RagType.GRAPH, source_collection=collection)
    index_config = GraphRagIndexConfig.objects.create()
    graph_rag = GraphRag.objects.create(base_rag_type=base_rag_type, index_config=index_config)
    return collection, graph_rag, index_config


@pytest.mark.django_db
class TestPurge:
    def test_purge_removes_a_binned_flow_and_its_nodes(self, graph):
        node = TaskNode.objects.create(graph=graph, node_name="task")
        graph.delete()

        PurgeService.purge(Graph.all_objects.get(pk=graph.pk), actor="test")

        assert not Graph.all_objects.filter(pk=graph.pk).exists()
        assert not TaskNode.all_objects.filter(pk=node.pk).exists()

    def test_purge_refuses_a_live_row(self, graph):
        with pytest.raises(NotInRecycleBinError):
            PurgeService.purge(graph, actor="test")

        assert Graph.objects.filter(pk=graph.pk).exists()

    def test_purge_of_a_collection_drops_its_unused_content(self, default_org):
        collection = SourceCollection.objects.create(org=default_org, collection_name="Old docs")
        content = DocumentContent.objects.create(content=b"old")
        DocumentMetadata.objects.create(
            source_collection=collection,
            document_content=content,
            file_name="old.txt",
            file_type="txt",
            file_size=3,
        )
        collection.delete()

        PurgeService.purge(SourceCollection.all_objects.get(collection_id=collection.collection_id), actor="test")

        assert not SourceCollection.all_objects.filter(collection_id=collection.collection_id).exists()
        assert not DocumentContent.objects.filter(id=content.id).exists()


@pytest.mark.django_db
class TestPurgeCollectionGraphRag:
    """The knowledge-service call runs on commit, so the tests run the commit callbacks."""

    def test_purge_drops_the_index_config_and_the_knowledge_index(
        self, default_org, django_capture_on_commit_callbacks
    ):
        collection, graph_rag, index_config = _collection_with_graph_rag(default_org)
        collection.delete()

        with mock.patch(KNOWLEDGE_DELETE) as knowledge_delete, django_capture_on_commit_callbacks(execute=True):
            PurgeService.purge(SourceCollection.all_objects.get(pk=collection.pk), actor="test")

        assert not GraphRag.all_objects.filter(pk=graph_rag.pk).exists()
        assert not GraphRagIndexConfig.objects.filter(pk=index_config.pk).exists()
        knowledge_delete.assert_called_once_with(strategy=RAGStrategy.GRAPH, rag_id=graph_rag.pk)

    @pytest.mark.parametrize("error", [ClientResourceNotFoundError("gone"), ClientNotAvailableError("down")])
    def test_a_knowledge_service_failure_does_not_undo_the_purge(
        self, default_org, error, django_capture_on_commit_callbacks
    ):
        collection, graph_rag, _ = _collection_with_graph_rag(default_org)
        collection.delete()

        with mock.patch(KNOWLEDGE_DELETE, side_effect=error), django_capture_on_commit_callbacks(execute=True):
            PurgeService.purge(SourceCollection.all_objects.get(pk=collection.pk), actor="test")

        assert not SourceCollection.all_objects.filter(pk=collection.pk).exists()
        assert not GraphRag.all_objects.filter(pk=graph_rag.pk).exists()

    def test_a_failed_purge_leaves_the_knowledge_index_alone(self, default_org, django_capture_on_commit_callbacks):
        collection, _, index_config = _collection_with_graph_rag(default_org)

        with (
            mock.patch(KNOWLEDGE_DELETE) as knowledge_delete,
            django_capture_on_commit_callbacks(execute=True) as callbacks,
            pytest.raises(NotInRecycleBinError),
        ):
            PurgeService.purge(collection, actor="test")

        assert callbacks == []
        knowledge_delete.assert_not_called()
        assert GraphRagIndexConfig.objects.filter(pk=index_config.pk).exists()


def _backdate(model, row, days):
    model.all_objects.filter(pk=row.pk).update(soft_deleted_at=timezone.now() - timedelta(days=days))


def _binned_flow(org, name, days_ago):
    """A deleted flow with one node, deleted `days_ago` days ago (flow and node share the time)."""
    graph = Graph.objects.create(org=org, name=name)
    node = TaskNode.objects.create(graph=graph, node_name="task")
    graph.delete()
    batch = Graph.all_objects.get(pk=graph.pk).soft_delete_batch
    for model in (Graph, TaskNode):
        model.all_objects.filter(soft_delete_batch=batch).update(
            soft_deleted_at=timezone.now() - timedelta(days=days_ago)
        )
    return graph, node


@pytest.fixture
def storage_manager():
    manager = StorageManager(InMemoryStorageBackend(organization_prefix=""))
    with mock.patch("tables.services.recycle_bin.purge_service.get_storage_manager", return_value=manager):
        yield manager


@pytest.fixture
def storage_org(db):
    return Organization.objects.create(name="Purge storage org")


@pytest.mark.django_db
class TestPurgeExpired:
    @pytest.fixture(autouse=True)
    def retention_seven_days(self, settings, storage_manager):
        settings.RECYCLE_BIN_RETENTION_DAYS = 7

    def test_an_expired_flow_goes_with_its_nodes(self, default_org):
        graph, node = _binned_flow(default_org, "Old", days_ago=8)

        result = PurgeService.purge_expired()

        assert result["tables.Graph"] == 1
        assert not Graph.all_objects.filter(pk=graph.pk).exists()
        assert not TaskNode.all_objects.filter(pk=node.pk).exists()

    def test_a_flow_still_within_retention_stays(self, default_org):
        graph, _ = _binned_flow(default_org, "Recent", days_ago=6)

        result = PurgeService.purge_expired()

        assert Graph.deleted_objects.filter(pk=graph.pk).exists()
        assert "tables.Graph" not in result

    def test_follows_the_retention_setting(self, default_org, settings):
        settings.RECYCLE_BIN_RETENTION_DAYS = 1
        graph, _ = _binned_flow(default_org, "Two days", days_ago=2)

        PurgeService.purge_expired()

        assert not Graph.all_objects.filter(pk=graph.pk).exists()

    def test_now_can_be_given(self, default_org):
        graph, _ = _binned_flow(default_org, "Today", days_ago=0)

        PurgeService.purge_expired(now=timezone.now() + timedelta(days=30))

        assert not Graph.all_objects.filter(pk=graph.pk).exists()

    def test_a_node_deleted_on_its_own_goes_and_its_live_flow_stays(self, default_org):
        graph = Graph.objects.create(org=default_org, name="Live")
        node = TaskNode.objects.create(graph=graph, node_name="removed")
        DeleteService.delete(node)
        _backdate(TaskNode, node, 8)
        assert TaskNode.deleted_objects.filter(pk=node.pk).exists()

        PurgeService.purge_expired()

        assert Graph.objects.filter(pk=graph.pk).exists()
        assert not TaskNode.all_objects.filter(pk=node.pk).exists()

    def test_legacy_rows_without_a_batch_expire_too(self, default_org):
        old, _ = _binned_flow(default_org, "Legacy old", days_ago=8)
        recent, _ = _binned_flow(default_org, "Legacy recent", days_ago=2)
        Graph.all_objects.filter(pk__in=[old.pk, recent.pk]).update(soft_delete_batch=None)

        PurgeService.purge_expired()

        assert not Graph.all_objects.filter(pk=old.pk).exists()
        assert Graph.deleted_objects.filter(pk=recent.pk).exists()

    def test_built_in_tools_without_an_org_expire(self):
        code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
        tool = PythonCodeTool.objects.create(name="Gone built-in", description="d", python_code=code, built_in=True)
        tool.delete()
        _backdate(PythonCodeTool, tool, 8)

        PurgeService.purge_expired()

        assert not PythonCodeTool.all_objects.filter(pk=tool.pk).exists()

    def test_an_expired_storage_batch_goes_with_its_trash_objects(self, storage_org, storage_manager):
        seed_file(storage_manager._backend, storage_org.id, "docs/a.txt", b"a")
        storage_manager.delete(storage_org.id, "docs/a.txt")
        row = StorageFile.all_objects.get(org=storage_org, path="docs/a.txt")
        _backdate(StorageFile, row, 8)

        result = PurgeService.purge_expired()

        assert result["tables.StorageFile"] == 1
        assert not StorageFile.all_objects.filter(pk=row.pk).exists()
        assert not any(".recycle-bin/" in key for key in storage_manager._backend._objects)

    def test_a_restored_storage_file_survives_its_batch_expiring(self, storage_org, storage_manager):
        seed_file(storage_manager._backend, storage_org.id, "docs/a.txt", b"a")
        seed_file(storage_manager._backend, storage_org.id, "docs/b.txt", b"b")
        storage_manager.delete(storage_org.id, "docs")
        StorageRecycleBinService(storage_manager).restore(
            storage_org.id, StorageFile.deleted_objects.get(org=storage_org, path="docs/a.txt").pk
        )
        StorageFile.deleted_objects.filter(org=storage_org).update(soft_deleted_at=timezone.now() - timedelta(days=8))

        PurgeService.purge_expired()

        assert StorageFile.objects.filter(org=storage_org, path="docs/a.txt").exists()
        assert not StorageFile.all_objects.filter(org=storage_org, path="docs/b.txt").exists()
        assert storage_manager._backend._objects[f"org_{storage_org.id}/docs/a.txt"][0] == b"a"

    def test_an_expired_collection_drops_content_only_it_used(self, default_org):
        mine = DocumentContent.objects.create(content=b"only mine")
        shared = DocumentContent.objects.create(content=b"shared")
        collection = SourceCollection.objects.create(org=default_org, collection_name="Old docs")
        live = SourceCollection.objects.create(org=default_org, collection_name="Live docs")
        for target, content, name in ((collection, mine, "m.txt"), (collection, shared, "s.txt"), (live, shared, "s.txt")):
            DocumentMetadata.objects.create(
                source_collection=target, document_content=content, file_name=name, file_type="txt", file_size=1
            )
        collection.delete()
        _backdate(SourceCollection, collection, 8)

        PurgeService.purge_expired()

        assert not SourceCollection.all_objects.filter(pk=collection.pk).exists()
        assert not DocumentContent.objects.filter(id=mine.id).exists()
        assert DocumentContent.objects.filter(id=shared.id).exists()

    def test_one_failing_root_does_not_stop_the_run_and_keeps_its_children(self, default_org):
        failing, failing_node = _binned_flow(default_org, "Fails", days_ago=8)
        other, _ = _binned_flow(default_org, "Goes", days_ago=8)
        real_purge = PurgeService.purge

        def fail_for_one(root, *, actor):
            if root.pk == failing.pk:
                raise RuntimeError("boom")
            real_purge(root, actor=actor)

        with mock.patch.object(PurgeService, "purge", side_effect=fail_for_one):
            PurgeService.purge_expired()

        assert not Graph.all_objects.filter(pk=other.pk).exists()
        assert Graph.deleted_objects.filter(pk=failing.pk).exists()
        # Still with its node: restoring the flow must bring the node back.
        assert TaskNode.deleted_objects.filter(pk=failing_node.pk).exists()

    def test_an_undeletable_row_does_not_block_the_rest_of_its_model(self, default_org):
        graph = Graph.objects.create(org=default_org, name="Live")
        nodes = [TaskNode.objects.create(graph=graph, node_name=f"removed {index}") for index in range(3)]
        for node in nodes:
            DeleteService.delete(node)
            _backdate(TaskNode, node, 8)
        stuck = min(nodes, key=lambda node: node.pk)  # in the first chunk on every run
        real_delete = PurgeService._delete_locked

        def refuse_the_stuck_one(model, expired, pks):
            if model is TaskNode and stuck.pk in pks:
                raise RuntimeError("protected")
            return real_delete(model, expired, pks)

        with mock.patch.object(PurgeService, "_delete_locked", side_effect=refuse_the_stuck_one):
            PurgeService.purge_expired()

        assert TaskNode.deleted_objects.filter(pk=stuck.pk).exists()
        assert not TaskNode.all_objects.filter(pk__in=[node.pk for node in nodes if node.pk != stuck.pk]).exists()

    def test_an_empty_bin_purges_nothing(self):
        assert PurgeService.purge_expired() == {}
