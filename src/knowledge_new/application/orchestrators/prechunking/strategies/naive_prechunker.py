from application.orchestrators.prechunking.base import AbstractPrechunker
from domain.errors import NoPreviewChunksProducedError
from domain.models import ChunkingConfig, PrechunkRequest, PrechunkResponse
from infrastructure.file_text_extractors import build_file_text_extractor
from infrastructure.naive.chunkers import build_chunker
from loguru import logger


class NaivePrechunker(AbstractPrechunker):
    async def on_execute(self, request: PrechunkRequest) -> PrechunkResponse:
        config = ChunkingConfig(
            chunk_strategy=request.chunk_strategy,
            chunk_size=request.chunk_size,
            chunk_overlap=request.chunk_overlap,
            extra=request.extra,
        )

        async with self.uow:
            content, extension = await self.uow.naive_rag_repo.get_document_content(
                rag_id=request.rag_id,
                document_id=request.document_id,
            )

        extractor = build_file_text_extractor(extension)
        text = await extractor.extract(content)

        chunker = build_chunker(config.chunk_strategy, config)
        preview_chunks = await chunker.chunk(text)

        if not preview_chunks:
            raise NoPreviewChunksProducedError(
                document_id=request.document_id, rag_id=request.rag_id
            )

        async with self.uow:
            await self.uow.naive_rag_repo.save_preview_chunks(
                document_id=request.document_id, chunks=preview_chunks
            )
            await self.uow.commit()

        logger.info(
            "Prechunked document(id={}) of rag(id={}): produced {} chunks.",
            request.document_id,
            request.rag_id,
            len(preview_chunks),
        )
        return PrechunkResponse(request=request, chunks=preview_chunks)
