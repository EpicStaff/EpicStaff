import os

import pytest
from domain.errors import FileTextExtractingError
from infrastructure.file_text_extractors.strategies.csv_extractor import CSVTextExtractor
from tests.conftest import offload_to_process


async def test_extracts_rows():
    assert await CSVTextExtractor().extract(b"a,b\nc,d") == "a,b\nc,d"


async def test_drops_empty_and_empty_first_field_rows():
    assert await CSVTextExtractor().extract(b"a,b\n\n,skip\nc,d") == "a,b\nc,d"


async def test_non_bytes_raises():
    with pytest.raises(FileTextExtractingError):
        await CSVTextExtractor().extract(None)


async def test_extract_runs_in_process():
    extractor = CSVTextExtractor()
    content = b"a,b\nc,d"
    inline = await extractor.extract(content)
    result, worker_pid = await offload_to_process(lambda: extractor.extract(content))
    assert result == inline
    assert worker_pid != os.getpid()
