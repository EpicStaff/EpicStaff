from application.ports import AbstractChunker
from domain.models import ChunkingConfig, PreviewChunk
from infrastructure.processing_run import run_in_process
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter


class MarkdownChunker(AbstractChunker):
    _HEADERS = (
        ("#", "Header 1"),
        ("##", "Header 2"),
        ("###", "Header 3"),
        ("####", "Header 4"),
        ("#####", "Header 5"),
        ("######", "Header 6"),
    )

    def __init__(self, config: ChunkingConfig):
        super().__init__(config)
        markdowm_params = self.config.extra.get("markdown", {})
        headers_to_split_on = markdowm_params.get("headers_to_split_on", None)
        return_each_line = markdowm_params.get("return_each_line", False)
        strip_headers = markdowm_params.get("strip_headers", False)

        self.markdown_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=self._init_headers(headers_to_split_on),
            return_each_line=return_each_line,
            strip_headers=strip_headers,
        )
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
        )

    @run_in_process
    def _chunk(self, text: str) -> list[PreviewChunk]:
        md_splits = self.markdown_splitter.split_text(text)
        result_text_splits = []
        for doc in md_splits:
            text_splits = self.text_splitter.split_text(doc.page_content)
            for chunk_text in text_splits:
                result_text_splits.append(PreviewChunk(text=chunk_text))
        return result_text_splits

    def _init_headers(self, headers: list[str]) -> list[tuple[str, str]]:
        if headers is not None:
            return [h for h in self._HEADERS if h[0] in headers]
        else:
            return []
