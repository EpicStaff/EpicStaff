from bs4 import BeautifulSoup

from error_handler import handle_error
from errors import FileTextExtractingError
from services.file_text_extractors.base import AbstractFileTextExtractor
from services.processing_run import run_in_process


class HTMLTextExtractor(AbstractFileTextExtractor):
    """Text extractor for HTML files."""

    @run_in_process
    def extract(self, content: bytes) -> str:
        """Extract HTML `content`, stripped of `script`, `style`, and `img` tags.

        Raises:
            FileTextExtractingError: If the content cannot be extracted.
        """
        with handle_error(Exception, FileTextExtractingError, self):
            html_content = content.decode("utf-8")
            soup = BeautifulSoup(html_content, "html.parser")

            for tag in soup(["script", "style", "img"]):
                tag.decompose()

            return str(soup)
