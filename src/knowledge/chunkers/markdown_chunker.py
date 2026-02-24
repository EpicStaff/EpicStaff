from chunkers.base_chunker import BaseChunker, BaseChunkData
from langchain_text_splitters import MarkdownHeaderTextSplitter
from langchain_text_splitters import RecursiveCharacterTextSplitter


class MarkdownChunker(BaseChunker):
    def __init__(self, chunk_size, chunk_overlap, additional_params):
        markdowm_params = additional_params.get("markdown", {})

        headers_to_split_on = markdowm_params.get("headers_to_split_on", None)
        return_each_line = markdowm_params.get("return_each_line", False)
        strip_headers = markdowm_params.get("strip_headers", False)

        self.markdown_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=self._init_headers(headers_to_split_on),
            return_each_line=return_each_line,
            strip_headers=strip_headers,
        )
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )

    def _init_headers(self, headers: list[str]) -> list[tuple[str, str]]:
        if headers is not None:
            HEADERS_TO_SPLIT_ON = [
                ("#", "Header 1"),
                ("##", "Header 2"),
                ("###", "Header 3"),
                ("####", "Header 4"),
                ("#####", "Header 5"),
                ("######", "Header 6"),
            ]

            return [h for h in HEADERS_TO_SPLIT_ON if h[0] in headers]
        else:
            return []

    def chunk(self, text: str) -> list[BaseChunkData]:
        md_splits = self.markdown_splitter.split_text(text)
        result_text_splits = []
        for doc in md_splits:
            text_splits = self.text_splitter.split_text(doc.page_content)
            for chunk_text in text_splits:
                result_text_splits.append(BaseChunkData(text=chunk_text))
        return result_text_splits
