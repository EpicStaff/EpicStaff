import re

from application.ports import AbstractChunker
from domain.models import ChunkingConfig, PreviewChunk
from infrastructure.processing_run import run_in_process


class CharacterChunker(AbstractChunker):
    def __init__(self, config: ChunkingConfig):
        super().__init__(config)
        self.chunk_size = self.config.chunk_size
        self.chunk_overlap = self.config.chunk_overlap
        self.regex_pattern = self.config.extra.get("character", {}).get("regex")

    @run_in_process
    def _chunk(self, text: str) -> list[PreviewChunk]:
        text = text.replace("\r", "")

        parts = self._split(text)

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

    def _split(self, text: str) -> list[str]:
        if not self.regex_pattern:
            return [text]
        try:
            return re.split(self.regex_pattern, text)
        except re.error:
            return re.split(re.escape(self.regex_pattern), text)
