from loguru import logger

from errors import (
    EmbedderUnavailableError,
    EmbeddingError,
    ChunkingError,
    FileTextExtractingError,
    NoDocumentsToIndexError,
    UnsupportedError,
)
from enums import IndexStatusEnum, DocumentStatusEnum, DocumentErrorCode
from models import IndexRequest, IndexedChunk
from orchestrators.indexing.base import AbstractIndexer
from database.unit_of_work import SQLAlchemyUnitOfWork
from services.chunkers import build_chunker
from services.embedders import build_embedder
from services.file_text_extractors import build_file_text_extractor
from services.indexing_error_classifier import IndexingErrorClassifier


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

        if not documents:
            raise NoDocumentsToIndexError(request.rag_id)

        async with uow:
            await uow.naive_rag_repo.update_rag_status(
                rag_id=request.rag_id,
                status=IndexStatusEnum.PROCESSING,
            )
            await uow.commit()

        has_completed_documents = False
        has_failed_documents = False

        for document in documents:
            if (
                document.status == DocumentStatusEnum.COMPLETED
                and not document.is_required_reindex()
            ):
                logger.debug(
                    "Skipping document(id={}): already indexed with current params",
                    document.id,
                )
                has_completed_documents = True
                continue

            try:
                if document.preview_chunks:
                    preview_chunks = document.preview_chunks
                else:
                    document.status = DocumentStatusEnum.CHUNKING
                    async with uow:
                        await uow.naive_rag_repo.update_document(
                            request.rag_id, document
                        )
                        await uow.commit()
                    extractor = build_file_text_extractor(document.extension)
                    text = await extractor.extract(document.content)
                    chuncker = build_chunker(
                        document.config.chunk_strategy, document.config
                    )
                    preview_chunks = await chuncker.chunk(text)
                    if preview_chunks:
                        document.status = DocumentStatusEnum.CHUNKED
                        async with uow:
                            await uow.naive_rag_repo.update_document(
                                request.rag_id, document
                            )
                            await uow.commit()

                if not preview_chunks:
                    logger.warning(
                        "Document(id={}) produced 0 chunks, marking failed",
                        document.id,
                    )
                    document.mark_failed(
                        error_code=DocumentErrorCode.NO_CHUNKS_PRODUCED,
                        error_message="Document produced 0 chunks",
                    )
                    has_failed_documents = True
                    async with uow:
                        await uow.naive_rag_repo.update_document(
                            request.rag_id, document
                        )
                        await uow.commit()
                    continue

                document.status = DocumentStatusEnum.INDEXING
                async with uow:
                    await uow.naive_rag_repo.update_document(request.rag_id, document)
                    await uow.commit()

                # TODO: embed batch of chunks instead of one per time.
                indexed_chunks = [
                    IndexedChunk(
                        **ph.model_dump(),
                        vector=await embedder.embed(ph.text),
                    )
                    for ph in preview_chunks
                ]

            except (
                FileTextExtractingError,
                ChunkingError,
                EmbeddingError,
                UnsupportedError,
            ) as exc:
                document.mark_failed(*IndexingErrorClassifier.classify(exc))
                has_failed_documents = True
                logger.warning("Could not index document(id={}): {}", document.id, exc)

            else:
                document.indexed_chunks = indexed_chunks
                document.mark_completed()
                has_completed_documents = True
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
