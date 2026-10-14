
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
    ],
)
async def test_decodes_content(content, expected):
    assert await FileTextExtractor().extract(content) == expected
