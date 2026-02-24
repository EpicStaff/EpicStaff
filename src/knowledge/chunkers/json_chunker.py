from chunkers.base_chunker import BaseChunker, BaseChunkData
from langchain_text_splitters import RecursiveJsonSplitter
import json


class JSONChunker(BaseChunker):
    def __init__(self, chunk_size, chunk_overlap, additional_params):
        self.chunk_overlap = chunk_overlap
        self.json_splitter = RecursiveJsonSplitter(max_chunk_size=chunk_size)

    def chunk(self, text: str) -> list[BaseChunkData]:
        json_obj = self._convert_text_to_json(text)
        text_chunks = self.json_splitter.split_text(json_obj)
        return [BaseChunkData(text=chunk) for chunk in text_chunks]

    def _convert_text_to_json(self, json_text: str) -> dict | list:
        return json.loads(json_text)
