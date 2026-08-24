from domain.models import (
    ChunkingConfig,
    Document,
    EmbeddingConfig,
    FoundChunk,
    IndexedChunk,
    PreviewChunk,
    Rag,
)
from infrastructure.database.models import (
    NaiveRag,
    NaiveRagChunk,
    NaiveRagDocumentConfig,
    NaiveRagEmbedding,
    NaiveRagPreviewChunk,
)


def naive_rag_orm_to_rag(orm_rag: NaiveRag) -> Rag:
    return Rag(
        id=orm_rag.naive_rag_id,
        status=orm_rag.rag_status,
        indexing_document_ids=set(orm_rag.indexing_document_config_ids),
        error_message=orm_rag.error_message,
        outdated_reasons=orm_rag.outdated_reasons or {},
    )


def naive_rag_doc_config_to_document(config: NaiveRagDocumentConfig) -> Document:
    metadata = config.document
    document = Document(
        id=config.naive_rag_document_id,
        name=metadata.file_name,
        content=metadata.document_content.content,
        config=ChunkingConfig(
            chunk_strategy=config.chunk_strategy,
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            extra=config.additional_params or {},
        ),
        status=config.status,
        preview_chunks=[
            PreviewChunk(
                text=pc.text,
                token_count=pc.token_count,
                overlap_start=pc.overlap_start_index,
                overlap_end=pc.overlap_end_index,
            )
            for pc in sorted(config.preview_chunks, key=lambda c: c.chunk_index)
        ],
        error_message=config.error_message,
    )

    if config.indexed_chunk_size is not None:
        document.last_indexing_config = ChunkingConfig(
            chunk_strategy=config.indexed_chunk_strategy,
            chunk_size=config.indexed_chunk_size,
            chunk_overlap=config.indexed_chunk_overlap,
            extra=config.indexed_additional_params or {},
        )

    return document


def embedding_row_to_embedding_config(
    provider_name: str, model_name: str
) -> EmbeddingConfig:
    return EmbeddingConfig(provider=provider_name.lower(), model=model_name, extra={})


def search_rows_to_found_chunks(rows, similarity_threshold: float) -> list[FoundChunk]:
    return [
        FoundChunk(
            order=r.chunk_index,
            similarity=round(r.similarity, 4),
            text=r.text,
            source=r.file_name or "",
        )
        for r in rows
        if r.similarity >= similarity_threshold
    ]


def naive_rag_update_values(rag: Rag) -> dict:
    return {
        "rag_status": rag.status,
        "indexing_document_config_ids": list(rag.indexing_document_ids),
        "error_message": rag.error_message,
        "outdated_reasons": rag.outdated_reasons or {},
    }


def document_update_values(document: Document) -> dict:
    config = document.last_indexing_config
    return {
        "status": document.status,
        "indexed_chunk_strategy": config.chunk_strategy if config else None,
        "indexed_chunk_size": config.chunk_size if config else None,
        "indexed_chunk_overlap": config.chunk_overlap if config else None,
        "indexed_additional_params": config.extra if config else None,
        "error_message": document.error_message,
    }


def preview_chunk_to_orm(
    document_id: int, chunk: PreviewChunk, index: int
) -> NaiveRagPreviewChunk:
    return NaiveRagPreviewChunk(
        naive_rag_document_config_id=document_id,
        text=chunk.text,
        chunk_index=index,
        token_count=chunk.token_count,
        overlap_start_index=chunk.overlap_start,
        overlap_end_index=chunk.overlap_end,
    )


def indexed_chunk_to_orm_pair(
    document_id: int, chunk: IndexedChunk, index: int
) -> tuple[NaiveRagChunk, NaiveRagEmbedding]:
    orm_chunk = NaiveRagChunk(
        naive_rag_document_config_id=document_id,
        text=chunk.text,
        chunk_index=index,
        token_count=chunk.token_count,
        overlap_start_index=chunk.overlap_start,
        overlap_end_index=chunk.overlap_end,
    )
    orm_embedding = NaiveRagEmbedding(
        naive_rag_document_config_id=document_id, vector=chunk.vector
    )
    return orm_chunk, orm_embedding
