from io import BytesIO

import pdfplumber
from application.ports import AbstractFileTextExtractor
from infrastructure.processing_run import run_in_process


class PDFTextExtractor(AbstractFileTextExtractor):
    @run_in_process
    def _extract(self, content: bytes) -> str:
        text_parts = []

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
        return content.lstrip().startswith(b"%PDF-")

    @staticmethod
    def _extract_page_text(page) -> str:
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
