from loguru import logger

from enums import DocumentStatusEnum
from errors import (
    FileTextExtractingError,
    ChunkingError,
    DocumentNotFound,
    UnsupportedError,
)
from models import PrechunkRequest, PrechunkResponse
from database.unit_of_work import SQLAlchemyUnitOfWork
from services.chunkers import build_chunker
from services.file_text_extractors import build_file_text_extractor
from services.indexing_error_classifier import IndexingErrorClassifier
from orchestrators.prechunking.base import AbstractPrechunker


class NaivePrechunker(AbstractPrechunker):
    """Naive prechunker that extracts and chunks a document for preview."""

    async def chunk(
        self, request: PrechunkRequest, uow: SQLAlchemyUnitOfWork
    ) -> PrechunkResponse:
        """Extract and chunk the document in `request`, storing its preview chunks.

        Args:
            request: Prechunk request identifying the RAG and document.
            uow: Unit of work providing repository access.

        Returns:
            The preview chunks produced for the document.

        Note:
            Extraction and chunking failures are recorded as the document's
            `FAILED` status rather than raised; a missing document raises instead.
        """
        logger.info(
            "Prechunking document(id={}) of RAG(id={})",
            request.document_id,
            request.rag_id,
        )

        async with uow:
            document = await uow.naive_rag_repo.get_document(
                rag_id=request.rag_id,
                document_id=request.document_id,
            )

        if document is None:
            logger.warning(
                "Document(id={}) not found in RAG(id={}), nothing to prechunk",
                request.document_id,
                request.rag_id,
            )
            raise DocumentNotFound(
                f"Document(id={request.document_id}) is not found from rag (id={request.rag_id})"
            )

        try:
            extractor = build_file_text_extractor(document.extension)
            text = await extractor.extract(document.content)

            chunker = build_chunker(document.config.chunk_strategy, document.config)
            preview_chunks = await chunker.chunk(text)

        except (FileTextExtractingError, ChunkingError, UnsupportedError) as exc:
            document.mark_failed(*IndexingErrorClassifier.classify(exc))
            logger.warning("Could not prechunk document(id={}): {}", document.id, exc)
        else:
            document.mark_chunked_if_new_config()
            document.preview_chunks = preview_chunks
            logger.info(
                "Prechunked document(id={}) into {} chunks",
                document.id,
                len(preview_chunks),
            )

        async with uow:
            await uow.naive_rag_repo.update_document(
                rag_id=request.rag_id,
                document=document,
            )
            if document.status == DocumentStatusEnum.CHUNKED:
                await uow.naive_rag_repo.save_preview_chunks(
                    document_id=document.id,
                    chunks=document.preview_chunks,
                )
            await uow.commit()

        return PrechunkResponse(
            request=request,
            chunks=document.preview_chunks,
        )
