"""Collection detail counts of document configs, chunks and embeddings per NaiveRag."""

import pytest
from django.utils import timezone
from django.db import connection
from django.test.utils import CaptureQueriesContext

from tables.models.knowledge_models import (
    DocumentContent,
    DocumentMetadata,
    NaiveRag,
    NaiveRagChunk,
    NaiveRagDocumentConfig,
    NaiveRagEmbedding,
    SourceCollection,
)
from tables.serializers.knowledge_serializers import SourceCollectionDetailSerializer
from tables.services.knowledge_services.collection_management_service import (
    CollectionManagementService,
)

pytestmark = pytest.mark.django_db


def add_document_config(naive_rag, file_name, chunks, embeddings):
    """Create a document config with `chunks` chunks, the first `embeddings` of them embedded."""
    document = DocumentMetadata.objects.create(
        source_collection=naive_rag.base_rag_type.source_collection,
        document_content=DocumentContent.objects.create(content=file_name.encode()),
        file_name=file_name,
        file_type="pdf",
        file_size=1,
    )
    document_config = NaiveRagDocumentConfig.objects.create(
        naive_rag=naive_rag,
        document=document,
        chunk_strategy="token",
        chunk_size=1000,
        chunk_overlap=150,
    )
    for index in range(chunks):
        chunk = NaiveRagChunk.objects.create(
            naive_rag_document_config=document_config, text="text", chunk_index=index
        )
        if index < embeddings:
            NaiveRagEmbedding.objects.create(
                naive_rag_document_config=document_config, chunk=chunk
            )
    return document_config


@pytest.fixture
def populated_naive_rag(naive_rag):
    # Distinct totals (3 configs, 9 chunks, 5 embeddings) so any multiplication shows.
    add_document_config(naive_rag, "a.pdf", chunks=4, embeddings=2)
    add_document_config(naive_rag, "b.pdf", chunks=3, embeddings=3)
    add_document_config(naive_rag, "c.pdf", chunks=2, embeddings=0)
    return naive_rag


def naive_summary(summaries, naive_rag_id):
    return next(
        summary
        for summary in summaries
        if summary["rag_type"] == "naive" and summary["rag_id"] == naive_rag_id
    )


def detail_summaries(collection):
    return SourceCollectionDetailSerializer(collection).data["rag_configurations"]


def service_summaries(collection):
    return CollectionManagementService.get_rag_configurations(collection.collection_id)


@pytest.fixture(params=[detail_summaries, service_summaries], ids=["detail", "service"])
def summaries_of(request):
    return request.param


def test_counts_are_not_multiplied_by_each_other(
    source_collection, populated_naive_rag, summaries_of
):
    summary = naive_summary(summaries_of(source_collection), populated_naive_rag.pk)

    assert summary["document_configs_count"] == 3
    assert summary["chunks_count"] == 9
    assert summary["embeddings_count"] == 5


def test_rag_with_configs_but_no_chunks_counts_zero(
    source_collection, naive_rag, summaries_of
):
    add_document_config(naive_rag, "empty.pdf", chunks=0, embeddings=0)

    summary = naive_summary(summaries_of(source_collection), naive_rag.pk)

    assert summary["document_configs_count"] == 1
    assert summary["chunks_count"] == 0
    assert summary["embeddings_count"] == 0


def test_rag_without_document_configs_counts_zero(
    source_collection, naive_rag, summaries_of
):
    summary = naive_summary(summaries_of(source_collection), naive_rag.pk)

    assert summary["document_configs_count"] == 0
    assert summary["chunks_count"] == 0
    assert summary["embeddings_count"] == 0


def test_two_rags_in_one_collection_do_not_mix_counts(
    source_collection, populated_naive_rag, test_embedding_config, summaries_of
):
    other_rag = NaiveRag.objects.create(
        base_rag_type=populated_naive_rag.base_rag_type,
        embedder=test_embedding_config,
    )
    # Creating a NaiveRag auto-adds a config per existing collection document (3 here).
    add_document_config(other_rag, "other.pdf", chunks=7, embeddings=6)

    summaries = summaries_of(source_collection)

    first = naive_summary(summaries, populated_naive_rag.pk)
    second = naive_summary(summaries, other_rag.pk)
    assert (first["document_configs_count"], first["chunks_count"], first["embeddings_count"]) == (
        3,
        9,
        5,
    )
    assert (
        second["document_configs_count"],
        second["chunks_count"],
        second["embeddings_count"],
    ) == (4, 7, 6)


def test_prefetch_chain_annotates_the_same_counts(source_collection, populated_naive_rag):
    collection = SourceCollection.objects.prefetch_related(
        *CollectionManagementService.rag_configurations_prefetch()
    ).get(pk=source_collection.pk)

    (base_rag_type,) = collection.rag_types.all()
    (naive_rag,) = base_rag_type.naive_rags.all()

    assert naive_rag.document_configs_count == 3
    assert naive_rag.chunks_count == 9
    assert naive_rag.embeddings_count == 5


def test_soft_deleted_chunks_and_embeddings_are_still_counted(
    source_collection, populated_naive_rag, summaries_of
):
    now = timezone.now()
    NaiveRagChunk.all_objects.filter(
        naive_rag_document_config__naive_rag=populated_naive_rag
    ).update(active=False, soft_deleted_at=now)
    NaiveRagEmbedding.all_objects.filter(
        naive_rag_document_config__naive_rag=populated_naive_rag
    ).update(active=False, soft_deleted_at=now)

    summary = naive_summary(summaries_of(source_collection), populated_naive_rag.pk)

    assert summary["chunks_count"] == 9
    assert summary["embeddings_count"] == 5


def test_chunks_and_embeddings_are_not_joined_in_the_query(populated_naive_rag):
    queryset = NaiveRag.objects.filter(pk=populated_naive_rag.pk).annotate(
        **CollectionManagementService.naive_rag_count_annotations()
    )

    with CaptureQueriesContext(connection) as queries:
        list(queryset)

    assert len(queries) == 1
    sql = queries[0]["sql"]
    chunk_table = NaiveRagChunk._meta.db_table
    embedding_table = NaiveRagEmbedding._meta.db_table
    config_table = NaiveRagDocumentConfig._meta.db_table
    # The subqueries read these tables with FROM, so any JOIN to them is the outer join.
    assert f'JOIN "{chunk_table}"' not in sql
    assert f'JOIN "{embedding_table}"' not in sql
    outer_sql = sql.split("(SELECT")[0] + sql.rsplit(")", 1)[-1]
    assert outer_sql.count(f'JOIN "{config_table}"') <= 1
