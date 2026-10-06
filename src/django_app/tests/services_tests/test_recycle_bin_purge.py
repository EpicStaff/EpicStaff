"""PurgeService: a binned root goes for good, with what cascades from it."""

from unittest import mock

import pytest

from src.shared.enums.knowledge_new import RAGStrategy
from tables.clients.errors import ClientNotAvailableError, ClientResourceNotFoundError
from tables.exceptions import NotInRecycleBinError
from tables.models import DocumentContent, DocumentMetadata, Graph, SourceCollection, TaskNode
from tables.models.knowledge_models import BaseRagType, GraphRag, GraphRagIndexConfig
from tables.services.recycle_bin.purge_service import PurgeService

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

        PurgeService.purge(Graph.all_objects.get(pk=graph.pk))

        assert not Graph.all_objects.filter(pk=graph.pk).exists()
        assert not TaskNode.all_objects.filter(pk=node.pk).exists()

    def test_purge_refuses_a_live_row(self, graph):
        with pytest.raises(NotInRecycleBinError):
            PurgeService.purge(graph)

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

        PurgeService.purge(SourceCollection.all_objects.get(collection_id=collection.collection_id))

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
            PurgeService.purge(SourceCollection.all_objects.get(pk=collection.pk))

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
            PurgeService.purge(SourceCollection.all_objects.get(pk=collection.pk))

        assert not SourceCollection.all_objects.filter(pk=collection.pk).exists()
        assert not GraphRag.all_objects.filter(pk=graph_rag.pk).exists()

    def test_a_failed_purge_leaves_the_knowledge_index_alone(self, default_org, django_capture_on_commit_callbacks):
        collection, _, index_config = _collection_with_graph_rag(default_org)

        with (
            mock.patch(KNOWLEDGE_DELETE) as knowledge_delete,
            django_capture_on_commit_callbacks(execute=True) as callbacks,
            pytest.raises(NotInRecycleBinError),
        ):
            PurgeService.purge(collection)

        assert callbacks == []
        knowledge_delete.assert_not_called()
        assert GraphRagIndexConfig.objects.filter(pk=index_config.pk).exists()
