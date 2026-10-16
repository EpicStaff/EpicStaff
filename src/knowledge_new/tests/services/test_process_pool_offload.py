"""Every chunker and extractor gives the same result when offloaded to the process pool.

A worker process imports the strategy afresh and receives it pickled, so a strategy
that is not importable at module level or holds something unpicklable fails here.
"""

import os

import pytest
from domain.enums import ChunkStrategyEnum
from infrastructure.file_text_extractors.strategies.csv_extractor import CSVTextExtractor
from infrastructure.file_text_extractors.strategies.docx_extractor import DOCXTextExtractor
from infrastructure.file_text_extractors.strategies.html_extractor import HTMLTextExtractor
from infrastructure.file_text_extractors.strategies.pdf_extractor import PDFTextExtractor
from infrastructure.file_text_extractors.strategies.text_extractor import FileTextExtractor
from infrastructure.naive.chunkers.strategies.character_chunker import CharacterChunker
from infrastructure.naive.chunkers.strategies.csv_chunker import CSVChunker
from infrastructure.naive.chunkers.strategies.html_chunker import HTMLChunker
from infrastructure.naive.chunkers.strategies.json_chunker import JSONChunker
from infrastructure.naive.chunkers.strategies.markdown_chunker import MarkdownChunker
from infrastructure.naive.chunkers.strategies.token_chunker import TokenChunker
from tests.conftest import offload_to_process
from tests.services.chunkers.conftest import make_config
from tests.services.file_text_extractors.test_docx_extractor import make_docx
from tests.services.file_text_extractors.test_pdf_extractor import MINIMAL_PDF


def _chunk(chunker_class, strategy, text, **config):
    chunker = chunker_class(make_config(strategy, **config))
    return lambda: chunker.chunk(text)


def _extract(extractor_class, content):
    extractor = extractor_class()
    return lambda: extractor.extract(content)


@pytest.mark.parametrize(
    "make_call",
    [
        _chunk(
            CharacterChunker,
            ChunkStrategyEnum.CHARACTER,
            "12345678-qwertyui,ASDFGHJK",
            chunk_size=4,
            chunk_overlap=2,
            extra={"character": {"regex": r"-|,"}},
        ),
        _chunk(
            CSVChunker,
            ChunkStrategyEnum.CSV,
            "h1,h2\na,b\nc,d\ne,f",
            extra={"file_name": "t.csv", "csv": {"rows_in_chunk": 2}},
        ),
        _chunk(
            HTMLChunker,
            ChunkStrategyEnum.HTML,
            "<h1>Title</h1><p>Hello.</p><h2>Sub</h2><p>Second.</p>",
            chunk_size=200,
            extra={"html": {"headers_to_split_on": ["h1", "h2"]}},
        ),
        _chunk(JSONChunker, ChunkStrategyEnum.JSON, '{"a": 1, "b": 2}', chunk_size=200),
        _chunk(
            MarkdownChunker,
            ChunkStrategyEnum.MARKDOWN,
            "# Title\nIntro text.\n## Section\nSection body text here.",
            chunk_size=200,
            extra={"markdown": {"headers_to_split_on": ["#", "##"]}},
        ),
        _chunk(
            TokenChunker,
            ChunkStrategyEnum.TOKEN,
            " ".join(f"word{i}" for i in range(40)),
            chunk_size=10,
            chunk_overlap=3,
        ),
        _extract(CSVTextExtractor, b"a,b\nc,d"),
        _extract(DOCXTextExtractor, make_docx("Hello", "World")),
        _extract(HTMLTextExtractor, b"<html><body><p>Hi</p></body></html>"),
        _extract(PDFTextExtractor, MINIMAL_PDF),
        _extract(FileTextExtractor, "héllo".encode()),
    ],
    ids=[
        "character-chunker",
        "csv-chunker",
        "html-chunker",
        "json-chunker",
        "markdown-chunker",
        "token-chunker",
        "csv-extractor",
        "docx-extractor",
        "html-extractor",
        "pdf-extractor",
        "text-extractor",
    ],
)
async def test_offloaded_result_matches_inline_result(make_call):
    inline_result = await make_call()

    offloaded_result, worker_pid = await offload_to_process(make_call)

    assert offloaded_result == inline_result
    assert worker_pid != os.getpid()
