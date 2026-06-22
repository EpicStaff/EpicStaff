from loguru import logger

from errors import (
    EmbedderUnavailableError,
    EmbeddingError,
    ChunkingError,
    FileTextExtractingError,
)
from enums import IndexStatusEnum, DocumentStatusEnum
from models import IndexRequest, IndexedChunk
from orchestrators.indexing.base import AbstractIndexer
from database.unit_of_work import SQLAlchemyUnitOfWork
from services.chunkers import build_chunker
from services.embedders import build_embedder
from services.file_text_extractors import build_file_text_extractor


class NaiveIndexer(AbstractIndexer):
    """Naive indexer that extracts, chunks, embeds, and stores each document."""

    async def index(self, request: IndexRequest, uow: SQLAlchemyUnitOfWork):
        """Extract, chunk, embed, and store every document of the RAG in `request`.

        Args:
            request: Indexing request identifying the RAG to index.
            uow: Unit of work providing repository access.

        Raises:
            EmbedderUnavailableError: If the RAG has no embedding config.

        Note:
            Per-document extraction, chunking, and embedding failures are recorded
            as the document's status rather than raised. The RAG ends `COMPLETED`
            when all documents succeed, `WARNING` when some fail, and `FAILED` when
            none complete. Documents with existing preview chunks are reused
            instead of re-extracted.
        """

        logger.info("Indexing RAG(id={})", request.rag_id)

        async with uow:
            embedding_config = await uow.naive_rag_repo.get_embedding_config(
                rag_id=request.rag_id
            )

        if embedding_config is None:
            logger.warning(
                "RAG(id={}) has no embedding config, cannot index", request.rag_id
            )
            raise EmbedderUnavailableError(
                f"No embedding config for rag_id={request.rag_id}"
            )

        embedder = build_embedder(embedding_config.provider, embedding_config)

        async with uow:
            documents = await uow.naive_rag_repo.get_all_documents(
                rag_id=request.rag_id
            )

        logger.info(
            "RAG(id={}) has {} documents to index", request.rag_id, len(documents)
        )

        has_completed_documents = False
        has_failed_documents = False
        for document in documents:
            try:
                if document.preview_chunks:
                    preview_chunks = document.preview_chunks
                else:
                    extractor = build_file_text_extractor(document.extension)
                    text = await extractor.extract(document.content)
                    chuncker = build_chunker(
                        document.config.chunk_strategy, document.config
                    )
                    preview_chunks = await chuncker.chunk(text)

                # TODO: embed batch of chunks instead of one per time.
                indexed_chunks = [
                    IndexedChunk(
                        **ph.model_dump(),
                        vector=await embedder.embed(ph.text),
                    )
                    for ph in preview_chunks
                ]

            except (FileTextExtractingError, ChunkingError, EmbeddingError) as exc:
                has_failed_documents = True
                document.status = DocumentStatusEnum.FAILED
                logger.warning("Could not index document(id={}): {}", document.id, exc)

            else:
                has_completed_documents = True
                document.indexed_chunks = indexed_chunks
                document.status = DocumentStatusEnum.COMPLETED
                logger.debug(
                    "Indexed document(id={}) into {} chunks (reused preview: {})",
                    document.id,
                    len(indexed_chunks),
                    bool(document.preview_chunks),
                )

            async with uow:
                await uow.naive_rag_repo.update_document(
                    rag_id=request.rag_id,
                    document=document,
                )
                if document.status == DocumentStatusEnum.COMPLETED:
                    await uow.naive_rag_repo.save_indexed_chunks(
                        document_id=document.id, chunks=document.indexed_chunks
                    )
                await uow.commit()

        if not has_completed_documents:
            indexing_status = IndexStatusEnum.FAILED
        elif has_failed_documents:
            indexing_status = IndexStatusEnum.WARNING
        else:
            indexing_status = IndexStatusEnum.COMPLETED

        async with uow:
            await uow.naive_rag_repo.update_rag_status(
                rag_id=request.rag_id,
                status=indexing_status,
            )
            await uow.commit()

        logger.info(
            "Finished indexing RAG(id={}) with status {}",
            request.rag_id,
            indexing_status,
        )
