import re


from error_handler import handle_error
from errors import ChunkingError
from models import ChunkingConfig, PreviewChunk
from services.chunkers.base import AbstractChunker
from services.processing_run import run_in_process


class CharacterChunker(AbstractChunker):
    """Character-count text chunker with optional regex pre-splitting."""

    def __init__(self, config: ChunkingConfig):
        super().__init__(config)
        self.chunk_size = self.config.chunk_size
        self.chunk_overlap = self.config.chunk_overlap
        self.regex_pattern = (
            self.config.extra.get("character", {}).get("regex") or r".+"
        )

    @run_in_process
    def chunk(self, text: str) -> list[PreviewChunk]:
        """Split `text` into fixed-size character windows.

        Splits on the configured regex, then slides a
        `chunk_size` window with `chunk_overlap` over each part.

        Raises:
            ChunkingError: If the text cannot be chunked.

        Note:
            An invalid regex pattern is logged and yields no chunks.
        """
        with handle_error(Exception, ChunkingError, text, self):
            text = text.replace("\r", "")

            parts = re.split(self.regex_pattern, text)

            chunks = []
            step = self.chunk_size - self.chunk_overlap
            for part in parts:
                part = part.strip()
                if part:
                    if len(part) <= self.chunk_overlap:
                        chunks.append(PreviewChunk(text=part))
                    else:
                        chunks.extend(
                            [
                                PreviewChunk(text=part[i : i + self.chunk_size])
                                for i in range(0, len(part) - self.chunk_overlap, step)
                            ]
                        )
            return chunks
