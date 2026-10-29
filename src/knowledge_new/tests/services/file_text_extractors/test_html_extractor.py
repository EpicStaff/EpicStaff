
from infrastructure.file_text_extractors.strategies.html_extractor import HTMLTextExtractor

SAMPLE_HTML = (
    b'<html><body><p>Hi</p><script>bad()</script><img src="x"><style>.c{}</style></body></html>'
)


async def test_strips_script_style_img():
    assert await HTMLTextExtractor().extract(SAMPLE_HTML) == "<html><body><p>Hi</p></body></html>"
