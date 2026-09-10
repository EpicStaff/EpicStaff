import os

import pytest
from domain.errors import FileTextExtractingError
from infrastructure.file_text_extractors.strategies.pdf_extractor import PDFTextExtractor
from tests.conftest import offload_to_process

MINIMAL_PDF = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 44>>stream
BT /F1 24 Tf 100 700 Td (Hello PDF) Tj ET
endstream endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
0000000000 65535 f
trailer<</Root 1 0 R/Size 6>>
%%EOF"""


async def test_extracts_text():
    assert await PDFTextExtractor().extract(MINIMAL_PDF) == "Hello PDF"


async def test_non_pdf_bytes_raises():
    with pytest.raises(FileTextExtractingError):
        await PDFTextExtractor().extract(b"not a pdf")


async def test_non_bytes_raises():
    with pytest.raises(FileTextExtractingError):
        await PDFTextExtractor().extract(None)


async def test_extract_runs_in_process():
    extractor = PDFTextExtractor()
    inline = await extractor.extract(MINIMAL_PDF)
    result, worker_pid = await offload_to_process(lambda: extractor.extract(MINIMAL_PDF))
    assert result == inline
    assert worker_pid != os.getpid()
