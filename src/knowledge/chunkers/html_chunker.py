import json
from chunkers.base_chunker import BaseChunker, BaseChunkData

from langchain_text_splitters import HTMLSemanticPreservingSplitter


class HTMLChunker(BaseChunker):
    def __init__(self, chunk_size, chunk_overlap, additional_params):
        """
        Initialize the chunker with the provided chunk size and overlap.
        Uses HTMLSemanticPreservingSplitter to split the HTML text while preserving semantic structure.

        Parameters:
            chunk_size (int): Maximum size of chunks
            chunk_overlap (int): Overlap between chunks
            additional_params (dict): Additional parameters for customizing the HTML splitter
        """

        html_params = additional_params.get("html", {})

        headers_to_split_on = html_params.get("headers_to_split_on", None)

        separators = html_params.get("separators", None)
        elements_to_preserve = html_params.get("elements_to_preserve", None)
        preserve_links = html_params.get("preserve_links", False)
        preserve_images = html_params.get("preserve_images", False)
        preserve_videos = html_params.get("preserve_videos", False)
        preserve_audio = html_params.get("preserve_audio", False)
        custom_handlers = html_params.get("custom_handlers", None)
        stopword_removal = html_params.get("stopword_removal", False)
        stopword_lang = html_params.get("stopword_lang", "english")
        normalize_text = html_params.get("normalize_text", False)
        external_metadata = html_params.get("external_metadata", None)
        allowlist_tags = html_params.get("allowlist_tags", None)
        denylist_tags = html_params.get("denylist_tags", None)
        preserve_parent_metadata = html_params.get("preserve_parent_metadata", False)

        self.splitter = HTMLSemanticPreservingSplitter(
            headers_to_split_on=self._init_headers(headers_to_split_on),
            max_chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
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

    def _init_headers(self, headers: list[str]) -> list[tuple[str, str]]:
        if headers is not None:
            HEADERS_TO_SPLIT_ON = [
                ("h1", "Header 1"),
                ("h2", "Header 2"),
                ("h3", "Header 3"),
                ("h4", "Header 4"),
                ("h5", "Header 5"),
                ("h6", "Header 6"),
            ]

            return [h for h in HEADERS_TO_SPLIT_ON if h[0] in headers]
        else:
            return []

    def _convert_to_dict(self, obj) -> dict | None:
        if isinstance(obj, dict):
            return obj
        if isinstance(obj, str):
            try:
                result = json.loads(obj)
                return result if isinstance(result, dict) else None
            except (json.JSONDecodeError, ValueError):
                return None
        return None

    def chunk(self, html_text: str) -> list[BaseChunkData]:
        documents = self.splitter.split_text(html_text)
        chunks = [
            BaseChunkData(
                text=f"{doc.metadata}\n{doc.page_content}"
                if doc.metadata
                else doc.page_content
            )
            for doc in documents
        ]

        return chunks
