
from infrastructure.file_text_extractors.strategies.csv_extractor import CSVTextExtractor


async def test_extracts_rows():
    assert await CSVTextExtractor().extract(b"a,b\nc,d") == "a,b\nc,d"


async def test_drops_empty_and_empty_first_field_rows():
    assert await CSVTextExtractor().extract(b"a,b\n\n,skip\nc,d") == "a,b\nc,d"
