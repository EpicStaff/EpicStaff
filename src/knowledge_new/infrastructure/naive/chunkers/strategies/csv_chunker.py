from application.ports import AbstractChunker
from domain.errors import UnsupportedError
from domain.models import ChunkingConfig, PreviewChunk
from infrastructure.processing_run import run_in_process


class CSVChunker(AbstractChunker):
    def __init__(self, config: ChunkingConfig):
        super().__init__(config)
        self.file_name = self.config.extra.get("file_name") or "undefined"
        csv_params = self.config.extra.get("csv", {})
        if not isinstance(csv_params, dict):
            raise UnsupportedError(that="csv params (must be an object)", got=csv_params)
        self.headers_level: int = csv_params.get("headers_level", 1)
        self.rows_in_chunk: int = csv_params.get("rows_in_chunk", 150)
        if (
            not isinstance(self.headers_level, int)
            or isinstance(self.headers_level, bool)
            or self.headers_level < 0
        ):
            raise UnsupportedError(
                that="csv headers_level (must be an integer of at least 0)",
                got=self.headers_level,
            )
        # A non-positive step never advances the chunking loop, which would exhaust memory.
        if (
            not isinstance(self.rows_in_chunk, int)
            or isinstance(self.rows_in_chunk, bool)
            or self.rows_in_chunk < 1
        ):
            raise UnsupportedError(
                that="csv rows_in_chunk (must be an integer of at least 1)",
                got=self.rows_in_chunk,
            )

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
