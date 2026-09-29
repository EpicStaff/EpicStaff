import json

from application.ports import AbstractChunker
from domain.models import ChunkingConfig, PreviewChunk
from infrastructure.processing_run import run_in_process
from langchain_text_splitters import HTMLSemanticPreservingSplitter


class HTMLChunker(AbstractChunker):
    _HEADERS = (
        ("h1", "Header 1"),
        ("h2", "Header 2"),
        ("h3", "Header 3"),
        ("h4", "Header 4"),
        ("h5", "Header 5"),
        ("h6", "Header 6"),
    )

    def __init__(self, config: ChunkingConfig):
        super().__init__(config)
        params = self.config.extra.get("html", {})
        headers_to_split_on = params.get("headers_to_split_on", None)
        separators = params.get("separators", None)
        elements_to_preserve = params.get("elements_to_preserve", None)
        preserve_links = params.get("preserve_links", False)
        preserve_images = params.get("preserve_images", False)
        preserve_videos = params.get("preserve_videos", False)
        preserve_audio = params.get("preserve_audio", False)
        custom_handlers = params.get("custom_handlers", None)
        stopword_removal = params.get("stopword_removal", False)
        stopword_lang = params.get("stopword_lang", "english")
        normalize_text = params.get("normalize_text", False)
        external_metadata = params.get("external_metadata", None)
        allowlist_tags = params.get("allowlist_tags", None)
        denylist_tags = params.get("denylist_tags", None)
        preserve_parent_metadata = params.get("preserve_parent_metadata", False)

        self.splitter = HTMLSemanticPreservingSplitter(
            headers_to_split_on=self._init_headers(headers_to_split_on),
            max_chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
            separators=separators,
            elements_to_preserve=elements_to_preserve,
            preserve_links=preserve_links,
            preserve_images=preserve_images,
            preserve_videos=preserve_videos,
            preserve_audio=preserve_audio,
            custom_handlers=custom_handlers,
            stopword_removal=stopword_removal,
            stopword_lang=stopword_lang,
            normalize_text=normalize_text,
            external_metadata=self._convert_to_dict(external_metadata),
            allowlist_tags=allowlist_tags,
            denylist_tags=denylist_tags,
            preserve_parent_metadata=preserve_parent_metadata,
        )

    @run_in_process
    def _chunk(self, text: str) -> list[PreviewChunk]:
        documents = self.splitter.split_text(text)
        chunks = [
            PreviewChunk(
                text=f"{doc.metadata}\n{doc.page_content}" if doc.metadata else doc.page_content
            )
            for doc in documents
        ]

        return chunks

    def _init_headers(self, headers: list[str]) -> list[tuple[str, str]]:
        if headers is not None:
            return [h for h in self._HEADERS if h[0] in headers]
        else:
            return []

    @staticmethod
    def _convert_to_dict(obj) -> dict | None:
        if isinstance(obj, dict):
            return obj
        if isinstance(obj, str):
            try:
                result = json.loads(obj)
                return result if isinstance(result, dict) else None
            except (json.JSONDecodeError, ValueError):
                return None
        return None
