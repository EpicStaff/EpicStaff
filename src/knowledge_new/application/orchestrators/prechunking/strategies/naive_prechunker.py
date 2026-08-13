from application.commands import RunPrechunk
from application.orchestrators.prechunking.base import AbstractPrechunkOrchestrator
from domain.errors import NoPreviewChunksProducedError
from infrastructure.file_text_extractors import build_file_text_extractor
from infrastructure.naive.chunkers import build_chunker
from loguru import logger


class NaivePrechunkOrchestrator(AbstractPrechunkOrchestrator):
    async def on_execute(self, command: RunPrechunk):
        config = command.chunking_config

        async with self.uow:
            content, extension = await self.uow.naive_rag_repo.get_document_content(
                rag_id=command.rag_id,
                document_id=command.document_id,
            )

        extractor = build_file_text_extractor(extension)
        text = await extractor.extract(content)

        chunker = build_chunker(config.chunk_strategy, config)
        preview_chunks = await chunker.chunk(text)

        if not preview_chunks:
            raise NoPreviewChunksProducedError(
                document_id=command.document_id, rag_id=command.rag_id
            )

        async with self.uow:
            await self.uow.naive_rag_repo.save_preview_chunks(
                document_id=command.document_id, chunks=preview_chunks
            )
            await self.uow.commit()

        logger.info(
            "Prechunked document(id={}) of rag(id={}): produced {} chunks.",
            command.document_id,
            command.rag_id,
            len(preview_chunks),
        )
