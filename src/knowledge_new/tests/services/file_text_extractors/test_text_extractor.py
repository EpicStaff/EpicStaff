import os

import pytest
from domain.errors import FileTextExtractingError
from infrastructure.file_text_extractors.strategies.text_extractor import FileTextExtractor
from tests.conftest import offload_to_process


@pytest.mark.parametrize(
    "content,expected",
    [
        (
            "héllo".encode(),
            "héllo",
        ),
        (
            b"caf\xe9",
            "café",
        ),
        (
            b"",
            "",
        ),
    ],
)
async def test_decodes_content(content, expected):
    assert await FileTextExtractor().extract(content) == expected


async def test_non_bytes_raises():
    with pytest.raises(FileTextExtractingError):
        await FileTextExtractor().extract(None)


async def test_extract_runs_in_process():
    extractor = FileTextExtractor()
    content = "héllo".encode()
    inline = await extractor.extract(content)
    result, worker_pid = await offload_to_process(lambda: extractor.extract(content))
    assert result == inline
    assert worker_pid != os.getpid()
