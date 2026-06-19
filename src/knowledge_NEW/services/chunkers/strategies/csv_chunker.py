from error_handler import handle_error
from errors import ChunkingError
from models import ChunkingConfig, PreviewChunk
from services.chunkers.base import AbstractChunker
from services.processing_run import run_in_process


class CSVChunker(AbstractChunker):
    """Row-count chunker for CSV text that repeats the header rows in each chunk."""

    def __init__(self, config: ChunkingConfig):
        super().__init__(config)
        self.file_name = self.config.extra.get("file_name") or "undefined"
        csv_params = self.config.extra.get("csv", {})
        self.headers_level: int = csv_params.get("headers_level", 1)
        self.rows_in_chunk: int = csv_params.get("rows_in_chunk", 150)

    @run_in_process
    def chunk(self, text: str) -> list[PreviewChunk]:
        """Split CSV `text` into row-count batches, each prefixed with the header rows.

        Raises:
            ChunkingError: If the text cannot be chunked.
        """
        with handle_error(Exception, ChunkingError, text, self):
            lines = text.strip().splitlines()
            headers = "\n".join(lines[: self.headers_level])
            raw_rows = lines[self.headers_level :]

            results = []
            start = 0
            end = self.rows_in_chunk
            while start < len(raw_rows):
                rows = raw_rows[start:end]
                text = f'File name: {self.file_name}\n\n{headers}\n{'\n'.join(rows)}'
                results.append(PreviewChunk(text=text))
                start = end
                end += self.rows_in_chunk

            return results
