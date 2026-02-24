from chunkers.base_chunker import BaseChunker, BaseChunkData
import re
from loguru import logger


class CharacterChunker(BaseChunker):
    def __init__(self, chunk_size, chunk_overlap, additional_params):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        character_params = additional_params.get("character", {})
        self.regex_pattern = character_params.get("regex", None)

    def chunk(self, text: str) -> list[BaseChunkData]:
        text = text.replace("\r", "")

        try:
            parts = re.split(self.regex_pattern, text) if self.regex_pattern else [text]
        except re.error as e:
            logger.error(f"Error with RegEx {self.regex_pattern}. {e}")
            return []

        chunks = []
        step = self.chunk_size - self.chunk_overlap
        for part in parts:
            part = part.strip()
            if part:
                chunks.extend(
                    [
                        BaseChunkData(text=part[i : i + self.chunk_size])
                        for i in range(0, len(part), step)
                    ]
                )
        return chunks
