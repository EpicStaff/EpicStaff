
import socket

import nltk
import nltk.data
import pytest
from domain.enums import ChunkStrategyEnum
from domain.errors import UnsupportedError
from domain.models import PreviewChunk
from infrastructure.naive.chunkers.strategies.html_chunker import HTMLChunker
from tests.conftest import offload_to_process
from tests.services.chunkers.conftest import make_config

SAMPLE_HTML = "<h1>Title</h1><p>Hello world paragraph.</p><h2>Sub</h2><p>Second section text.</p>"


def build_chunker(
    chunk_size: int = 200, chunk_overlap: int = 0, extra: dict | None = None
) -> HTMLChunker:
    config = make_config(
        ChunkStrategyEnum.HTML,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        extra=extra or {},
    )
    return HTMLChunker(config)


async def test_chunk_prefixes_metadata_when_split_on_headers():
    chunker = build_chunker(extra={"html": {"headers_to_split_on": ["h1", "h2"]}})
    chunks = await chunker.chunk(SAMPLE_HTML)
    assert chunks == [
        PreviewChunk(text="{'Header 1': 'Title'}\nHello world paragraph."),
        PreviewChunk(text="{'Header 2': 'Sub'}\nSecond section text."),
    ]


async def test_chunk_without_headers_has_no_metadata_prefix():
    chunker = build_chunker()
    chunks = await chunker.chunk(SAMPLE_HTML)
    assert chunks == [PreviewChunk(text="Title Hello world paragraph. Sub Second section text.")]


@pytest.mark.parametrize("text", ["", "just plain text with no tags"])
async def test_chunk_returns_empty_for_no_content(text):
    chunker = build_chunker()
    assert await chunker.chunk(text) == []


STOPWORD_HTML = "<p>The cat is on the mat.</p>"
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture
def offline_nltk(monkeypatch, tmp_path):
    """Local stopwords corpus on the NLTK path; any download or socket connect fails the test."""
    corpus_dir = tmp_path / "corpora" / "stopwords"
    corpus_dir.mkdir(parents=True)
    (corpus_dir / "english").write_text("the\nis\non\n", encoding="utf8")
    (corpus_dir / "README").write_text("not a language\n", encoding="utf8")

    def fail_download(*args, **kwargs):
        raise AssertionError("nltk.download must not be called at runtime")

    real_connect = socket.socket.connect
    real_getaddrinfo = socket.getaddrinfo

    # The event loop and process pool talk over loopback; only outbound traffic is refused.
    def connect_loopback_only(sock, address, *args, **kwargs):
        if isinstance(address, tuple) and address[0] not in _LOOPBACK_HOSTS:
            raise AssertionError(f"no network access is allowed while chunking: {address}")
        return real_connect(sock, address, *args, **kwargs)

    def resolve_loopback_only(host, *args, **kwargs):
        if host not in _LOOPBACK_HOSTS:
            raise AssertionError(f"no DNS lookup is allowed while chunking: {host}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(nltk, "download", fail_download)
    monkeypatch.setattr(socket.socket, "connect", connect_loopback_only)
    monkeypatch.setattr(socket, "getaddrinfo", resolve_loopback_only)
    monkeypatch.setattr(nltk.data, "path", [str(tmp_path)])
    yield tmp_path


async def test_stopword_removal_uses_local_corpus_without_network(offline_nltk):
    chunker = build_chunker(extra={"html": {"stopword_removal": True}})
    assert await chunker.chunk(STOPWORD_HTML) == [PreviewChunk(text="The cat mat.")]


async def test_stopword_removal_applies_before_size_split(offline_nltk):
    # "cat mat" (7 chars) fits one chunk only because stopwords were removed first.
    chunker = build_chunker(
        chunk_size=7, extra={"html": {"stopword_removal": True, "normalize_text": True}}
    )
    assert await chunker.chunk(STOPWORD_HTML) == [PreviewChunk(text="cat mat")]


async def test_stopwords_kept_when_removal_disabled(offline_nltk):
    chunker = build_chunker()
    assert await chunker.chunk(STOPWORD_HTML) == [PreviewChunk(text="The cat is on the mat.")]


async def test_stopword_removal_survives_process_pool_offload(offline_nltk):
    chunker = build_chunker(extra={"html": {"stopword_removal": True}})
    chunks, _ = await offload_to_process(lambda: chunker.chunk(STOPWORD_HTML))
    assert chunks == [PreviewChunk(text="The cat mat.")]


def test_missing_corpus_raises_lookup_error_without_download(offline_nltk, monkeypatch, tmp_path):
    monkeypatch.setattr(nltk.data, "path", [str(tmp_path / "empty")])
    with pytest.raises(LookupError):
        build_chunker(extra={"html": {"stopword_removal": True}})


@pytest.mark.parametrize("language", ["klingon", "README", "../stopwords/english", ""])
def test_unknown_stopword_language_is_unsupported(offline_nltk, language):
    with pytest.raises(UnsupportedError):
        build_chunker(extra={"html": {"stopword_removal": True, "stopword_lang": language}})
