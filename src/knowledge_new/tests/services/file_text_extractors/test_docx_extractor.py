from io import BytesIO

import pytest
from docx import Document
from domain.errors import FileTextExtractingError
from infrastructure.file_text_extractors.strategies.docx_extractor import DOCXTextExtractor


def make_docx(*paragraphs: str) -> bytes:
    buf = BytesIO()
    document = Document()
    for text in paragraphs:
        document.add_paragraph(text)
    document.save(buf)
    return buf.getvalue()


async def test_joins_paragraphs_and_drops_blank():
    content = make_docx("Hello", "", "World")
    assert await DOCXTextExtractor().extract(content) == "Hello\nWorld"


async def test_no_paragraphs_returns_empty():
    assert await DOCXTextExtractor().extract(make_docx()) == ""


async def test_non_docx_bytes_raises():
    with pytest.raises(FileTextExtractingError):
        await DOCXTextExtractor().extract(b"not a docx")
