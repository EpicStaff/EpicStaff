"""The `indexing_usage` column the knowledge service writes is exposed read-only."""

import pytest

from tables.serializers.graph_rag_serializers import (
    GraphRagDetailSerializer,
    GraphRagSerializer,
)
from tables.serializers.naive_rag_serializers import NaiveRagSerializer
from tables.services.knowledge_services.collection_management_service import (
    CollectionManagementService,
)

pytestmark = pytest.mark.django_db

USAGE = {
    "last_run": {
        "embedding_tokens": 120,
        "llm_input_tokens": None,
        "llm_output_tokens": None,
        "cost_usd": 0.0024,
        "completed_at": "2026-10-13T08:00:00Z",
    },
    "total": {
        "embedding_tokens": 340,
        "llm_input_tokens": None,
        "llm_output_tokens": None,
        "cost_usd": 0.0068,
    },
}


def test_new_rags_start_with_empty_usage(naive_rag, graph_rag):
    naive_rag.refresh_from_db()
    graph_rag.refresh_from_db()

    assert naive_rag.indexing_usage == {}
    assert graph_rag.indexing_usage == {}


def test_naive_rag_serializer_exposes_stored_usage(naive_rag):
    naive_rag.indexing_usage = USAGE
    naive_rag.save(update_fields=["indexing_usage"])

    assert NaiveRagSerializer(naive_rag).data["indexing_usage"] == USAGE


def test_graph_rag_serializers_expose_stored_usage(graph_rag):
    graph_rag.indexing_usage = USAGE
    graph_rag.save(update_fields=["indexing_usage"])

    assert GraphRagSerializer(graph_rag).data["indexing_usage"] == USAGE
    assert GraphRagDetailSerializer(graph_rag).fields["indexing_usage"].read_only


def test_usage_is_read_only_in_the_rag_serializers(naive_rag, graph_rag):
    serializer = NaiveRagSerializer(naive_rag, data={"indexing_usage": USAGE}, partial=True)
    assert serializer.is_valid()
    assert "indexing_usage" not in serializer.validated_data
    assert GraphRagSerializer(graph_rag).fields["indexing_usage"].read_only


def test_collection_rag_summaries_carry_usage(source_collection, naive_rag, graph_rag):
    naive_rag.indexing_usage = USAGE
    naive_rag.save(update_fields=["indexing_usage"])

    summaries = CollectionManagementService.get_rag_configurations(
        source_collection.collection_id
    )

    by_type = {summary["rag_type"]: summary for summary in summaries}
    assert by_type["naive"]["indexing_usage"] == USAGE
    assert by_type["graph"]["indexing_usage"] == {}
