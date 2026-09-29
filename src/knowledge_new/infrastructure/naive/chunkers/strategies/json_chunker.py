import json

from application.ports import AbstractChunker
from domain.models import ChunkingConfig, PreviewChunk
from infrastructure.processing_run import run_in_process
from langchain_text_splitters import RecursiveJsonSplitter


class JSONChunker(AbstractChunker):
    def __init__(self, config: ChunkingConfig):
        super().__init__(config)
        self.chunk_overlap = self.config.chunk_overlap
        self.json_splitter = RecursiveJsonSplitter(max_chunk_size=config.chunk_size)

    @run_in_process
    def _chunk(self, text: str) -> list[PreviewChunk]:
        data = json.loads(text)
        text_chunks = self.json_splitter.split_text(data)
        return [PreviewChunk(text=chunk) for chunk in text_chunks]
