from chonkie import TokenChunker as ChonkieTokenChunker

from error_handler import handle_error
from errors import ChunkingError
from models import PreviewChunk
from services.chunkers.base import AbstractChunker
from services.processing_run import run_in_process


class TokenChunker(AbstractChunker):
    """Token-count text chunker."""

    @run_in_process
    def chunk(self, text: str) -> list[PreviewChunk]:
        """Split `text` into token-bounded chunks, recording per-chunk overlap.

        Raises:
            ChunkingError: If the text cannot be chunked.
        """
        with handle_error(Exception, ChunkingError, text, self):
            text_splitter = ChonkieTokenChunker(
                tokenizer="gpt2",
                chunk_size=self.config.chunk_size,
                chunk_overlap=self.config.chunk_overlap,
            )
            chunks = text_splitter.chunk(text)

            overlaps = []
            for i in range(len(chunks) - 1):
                overlap = chunks[i].end_index - chunks[i + 1].start_index
                overlaps.append(overlap)

            token_chunks = []
            for i, chunk in enumerate(chunks):
                token_chunks.append(
                    PreviewChunk(
                        text=chunk.text,
                        token_count=chunk.token_count,
                        overlap_start=overlaps[i - 1] if i > 0 else None,
                        overlap_end=overlaps[i] if i < len(overlaps) else None,
                    )
                )
            return token_chunks
