import json

from application.ports import AbstractChunker
from domain.errors import UnsupportedError
from domain.models import ChunkingConfig, PreviewChunk
from infrastructure.processing_run import run_in_process
from langchain_text_splitters import HTMLSemanticPreservingSplitter


def _load_stopwords(language: str) -> frozenset[str]:
    """Read the stopword list for `language` from the local NLTK data path.

    Only `nltk.data.path` (which includes `$NLTK_DATA`) is searched; nothing is
    downloaded. The image bakes the corpus at build time.

    Raises:
        LookupError: The stopwords corpus is not installed on the data path.
        UnsupportedError: The corpus has no list for `language`.
    """
    # Imported here, not at module level: process-pool workers import this
    # module to look up `_chunk` and only need the pickled stopword set. With a
    # spawn start method and the venv inside the CWD (local runs), nltk's
    # import-security hook would block its own `regex` import in the worker.
    import nltk.data
    from nltk.corpus.reader import WordListCorpusReader

    corpus = WordListCorpusReader(
        nltk.data.find("corpora/stopwords"), r"(?!README|\.).*", encoding="utf8"
    )
    # Checking against fileids also keeps a caller-supplied language from
    # naming a path outside the corpus.
    if language not in corpus.fileids():
        raise UnsupportedError(that="stopword language", got=language)
    return frozenset(corpus.words(language))


class _LocalStopwordHTMLSplitter(HTMLSemanticPreservingSplitter):
    """HTML splitter that removes stopwords from a list the caller supplies.

    langchain's own `stopword_removal=True` calls `nltk.download("stopwords")`
    in its constructor, which fetches the NLTK index from GitHub on every call,
    even when the corpus is already on disk. Here the parent always runs with
    stopword removal off and the same filter is applied at the same point,
    `_normalize_and_clean_text` (langchain-text-splitters 1.1.2), so chunk
    boundaries are computed on the filtered text exactly as before.
    """

    def __init__(self, *, stopwords: frozenset[str] | None, **kwargs):
        super().__init__(stopword_removal=False, **kwargs)
        self._local_stopwords = stopwords

    def _normalize_and_clean_text(self, text: str) -> str:
        text = super()._normalize_and_clean_text(text)
        if self._local_stopwords is None:
            return text
        return " ".join(word for word in text.split() if word not in self._local_stopwords)


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

        self.splitter = _LocalStopwordHTMLSplitter(
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
            stopwords=_load_stopwords(stopword_lang) if stopword_removal else None,
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
