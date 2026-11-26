
import pytest
from infrastructure.file_text_extractors.strategies.text_extractor import FileTextExtractor


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
        (
            b'\xef\xbb\xbf{"a": 1}',
            '{"a": 1}',
        ),
    ],
    ids=["utf-8", "latin-1", "empty", "byte-order-mark"],
)
async def test_decodes_content(content, expected):
    assert await FileTextExtractor().extract(content) == expected
