from io import BytesIO

from docx import Document

from error_handler import handle_error
from errors import FileTextExtractingError
from services.file_text_extractors.base import AbstractFileTextExtractor
from services.processing_run import run_in_process


class DOCXTextExtractor(AbstractFileTextExtractor):
    """Text extractor for DOCX files."""

    @run_in_process
    def extract(self, content: bytes) -> str:
        """Extract text from DOCX `content`, one paragraph per line.

        Returns:
            The document text, or an empty string when it has no paragraphs.

        Raises:
            FileTextExtractingError: If the content cannot be extracted.
        """
        with handle_error(Exception, FileTextExtractingError, self):
            docx_file = BytesIO(content)
            document = Document(docx_file)

            paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
            if paragraphs:
                return "\n".join(paragraphs)
            return ""
