import os

import pytest
from domain.errors import FileTextExtractingError
from infrastructure.file_text_extractors.strategies.html_extractor import HTMLTextExtractor
from tests.conftest import offload_to_process

SAMPLE_HTML = (
    b'<html><body><p>Hi</p><script>bad()</script><img src="x"><style>.c{}</style></body></html>'
)


async def test_strips_script_style_img():
    assert await HTMLTextExtractor().extract(SAMPLE_HTML) == "<html><body><p>Hi</p></body></html>"


async def test_non_bytes_raises():
    with pytest.raises(FileTextExtractingError):
        await HTMLTextExtractor().extract(None)


async def test_extract_runs_in_process():
    extractor = HTMLTextExtractor()
    inline = await extractor.extract(SAMPLE_HTML)
    result, worker_pid = await offload_to_process(lambda: extractor.extract(SAMPLE_HTML))
    assert result == inline
    assert worker_pid != os.getpid()
