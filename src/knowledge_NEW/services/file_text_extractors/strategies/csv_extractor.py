import csv
from io import StringIO

from error_handler import handle_error
from errors import FileTextExtractingError
from services.file_text_extractors.base import AbstractFileTextExtractor
from services.processing_run import run_in_process


class CSVTextExtractor(AbstractFileTextExtractor):
    """Text extractor for CSV files."""

    @run_in_process
    def extract(self, content: bytes) -> str:
        """Extract text from CSV `content`, one comma-joined row per line.

        Raises:
            FileTextExtractingError: If the content cannot be extracted.
        """
        with handle_error(Exception, FileTextExtractingError, self):
            text_content = content.decode("utf-8")
            csv_file = StringIO(text_content)
            reader = csv.reader(csv_file)
            extracted_rows = [
                ",".join(r) for r in reader if r and len(r[0].replace(",", "")) != 0
            ]
            return "\n".join(extracted_rows)
