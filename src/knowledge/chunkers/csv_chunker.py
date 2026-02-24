from chunkers.base_chunker import BaseChunker, BaseChunkData
import math


class CSVChunker(BaseChunker):
    """CSV chunker based on TokenTextSplitter"""

    def __init__(self, chunk_size, chunk_overlap, additional_params):
        self.file_name = additional_params.get("file_name", None)
        csv_params = additional_params.get("csv", {})

        self.headers_level: int = csv_params.get("headers_level", 1)
        self.rows_in_chunk: int = csv_params.get("rows_in_chunk", 150)

    def chunk(self, text: str) -> list[BaseChunkData]:
        lines = text.strip().splitlines()

        headers = lines[: self.headers_level]
        data_lines = lines[self.headers_level :]

        num_chunks = math.ceil(len(data_lines) / self.rows_in_chunk)
        results = []

        for i in range(num_chunks):
            start_idx = i * self.rows_in_chunk
            end_idx = start_idx + self.rows_in_chunk

            chunk_data_lines = data_lines[start_idx:end_idx]

            list_chunk_with_headers = headers + chunk_data_lines
            chunk_with_headers = "\n".join(list_chunk_with_headers)
            full_chunk_text = f"File name: {self.file_name} \n\n{chunk_with_headers}"

            results.append(BaseChunkData(text=full_chunk_text))

        return results
