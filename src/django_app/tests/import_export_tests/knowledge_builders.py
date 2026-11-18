"""Builders for knowledge collections, shared by the export and import tests."""

from django.utils import timezone

from tables.models.knowledge_models import (
    BaseRagType,
    DocumentContent,
    DocumentMetadata,
    GraphRag,
    NaiveRag,
    NaiveRagChunk,
    NaiveRagDocumentConfig,
    NaiveRagEmbedding,
)

COMPLETED_CONFIG = NaiveRagDocumentConfig.NaiveRagDocumentStatus.COMPLETED


def bin_row(row) -> None:
    """Move a row to the recycle bin the way the delete service leaves it."""
    type(row).all_objects.filter(pk=row.pk).update(active=False, soft_deleted_at=timezone.now())


def make_document(collection, name: str, content: bytes | None) -> DocumentMetadata:
    stored = DocumentContent.objects.create(content=content) if content is not None else None
    return DocumentMetadata.objects.create(
        source_collection=collection,
        document_content=stored,
        file_name=name,
        file_type="txt",
        file_size=len(content or b""),
    )


def make_naive_rag(collection, embedder=None) -> NaiveRag:
    base = BaseRagType.objects.create(
        source_collection=collection, rag_type=BaseRagType.RagType.NAIVE
    )
    return NaiveRag.objects.create(base_rag_type=base, embedder=embedder)


def make_config(naive_rag, document, **fields) -> NaiveRagDocumentConfig:
    # Creating a NaiveRag already adds a config for every document it can see.
    config, _ = NaiveRagDocumentConfig.objects.update_or_create(
        naive_rag=naive_rag, document=document, defaults=fields
    )
    return config


def make_graph_rag(collection, *, status, embedder=None, llm=None, index_config=None) -> GraphRag:
    base = BaseRagType.objects.create(
        source_collection=collection, rag_type=BaseRagType.RagType.GRAPH
    )
    return GraphRag.objects.create(
        base_rag_type=base,
        embedder=embedder,
        llm=llm,
        index_config=index_config,
        rag_status=status,
    )


def make_chunk(config, index: int, text: str, vector: list[float] | None) -> None:
    chunk = NaiveRagChunk.objects.create(
        naive_rag_document_config=config,
        chunk_index=index,
        text=text,
        token_count=len(text),
        overlap_start_index=0,
        overlap_end_index=2,
        metadata={"page": index + 1},
    )
    if vector is not None:
        NaiveRagEmbedding.objects.create(
            naive_rag_document_config=config, chunk=chunk, vector=vector
        )
