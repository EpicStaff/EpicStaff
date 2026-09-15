from application.ports import AbstractChunker
from domain.models import ChunkingConfig, PreviewChunk
from infrastructure.processing_run import run_in_process


class CSVChunker(AbstractChunker):
    def __init__(self, config: ChunkingConfig):
        super().__init__(config)
        self.file_name = self.config.extra.get("file_name") or "undefined"
        csv_params = self.config.extra.get("csv", {})
        self.headers_level: int = csv_params.get("headers_level", 1)
        self.rows_in_chunk: int = csv_params.get("rows_in_chunk", 150)

    @run_in_process
    def _chunk(self, text: str) -> list[PreviewChunk]:
        lines = text.strip().splitlines()
        headers = "\n".join(lines[: self.headers_level])
        raw_rows = lines[self.headers_level :]

        results = []
        start = 0
        end = self.rows_in_chunk
        while start < len(raw_rows):
            rows = raw_rows[start:end]
            text = f"File name: {self.file_name}\n\n{headers}\n{'\n'.join(rows)}"
            results.append(PreviewChunk(text=text))
            start = end
            end += self.rows_in_chunk

        return results
