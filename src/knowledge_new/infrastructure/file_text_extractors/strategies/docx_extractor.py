from io import BytesIO

from application.ports import AbstractFileTextExtractor
from docx import Document
from infrastructure.processing_run import run_in_process


class DOCXTextExtractor(AbstractFileTextExtractor):
    @run_in_process
    def _extract(self, content: bytes) -> str:
        docx_file = BytesIO(content)
        document = Document(docx_file)

        paragraphs = [
            p.text
            for p in document.paragraphs
            if p.text.strip()
        ]  # fmt: skip
        if paragraphs:
            return "\n".join(paragraphs)
        return ""
