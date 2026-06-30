from bs4 import BeautifulSoup
from services.file_text_extractors.base import AbstractFileTextExtractor
from services.processing_run import run_in_process


class HTMLTextExtractor(AbstractFileTextExtractor):
    @run_in_process
    def _extract(self, content: bytes) -> str:
        html_content = content.decode("utf-8")
        soup = BeautifulSoup(html_content, "html.parser")

        for tag in soup(["script", "style", "img"]):
            tag.decompose()

        return str(soup)
