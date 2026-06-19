from io import BytesIO

import pdfplumber

from error_handler import handle_error
from errors import FileTextExtractingError
from services.file_text_extractors.base import AbstractFileTextExtractor
from services.processing_run import run_in_process


class PDFTextExtractor(AbstractFileTextExtractor):
    """Text extractor for PDF files."""

    @run_in_process
    def extract(self, content: bytes) -> str:
        """Extract text from PDF `content`, one block per page.

        Returns:
            The document text, or an empty string when it has no extractable text.

        Raises:
            FileTextExtractingError: If the content cannot be extracted.
        """
        text_parts = []

        with handle_error(Exception, FileTextExtractingError, self):
            with pdfplumber.open(BytesIO(content)) as pdf_document:
                for page in pdf_document.pages:
                    page_text = self._extract_page_text(page)
                    if page_text:
                        text_parts.append(page_text)

        if text_parts:
            return "\n\n".join(text_parts)
        return ""

    @staticmethod
    def _is_valid_pdf(content: bytes) -> bool:
        """Return `True` when `content` starts with the PDF magic bytes.

        Args:
            content: Raw file bytes to inspect.
        """
        # Strip leading whitespace and check for PDF signature
        return content.lstrip().startswith(b"%PDF-")

    @staticmethod
    def _extract_page_text(page) -> str:
        """Extract `page` text, approximating PyMuPDF's line and paragraph breaks.

        Args:
            page: A `pdfplumber` page to extract lines from.

        Returns:
            The page text, or an empty string when the page has no lines.
        """
        lines = page.extract_text_lines(
            strip=True,
            return_chars=False,
            x_tolerance=3,
            y_tolerance=3,
        )
        if not lines:
            return ""
        if len(lines) == 1:
            return lines[0]["text"]

        spacings = [
            lines[i]["top"] - lines[i - 1]["top"]
            for i in range(1, len(lines))
            if lines[i]["top"] > lines[i - 1]["top"]
        ]
        if not spacings:
            return "\n".join(line["text"] + " " for line in lines).rstrip(" ")

        median_spacing = sorted(spacings)[len(spacings) // 2]
        paragraph_threshold = median_spacing * 1.5

        parts = [lines[0]["text"] + " "]
        for i in range(1, len(lines)):
            spacing = lines[i]["top"] - lines[i - 1]["top"]
            if spacing > paragraph_threshold:
                parts.append(" ")
            parts.append(lines[i]["text"] + " ")

        return "\n".join(parts).rstrip(" ")
