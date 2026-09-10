import csv
from io import StringIO

from application.ports import AbstractFileTextExtractor
from infrastructure.processing_run import run_in_process


class CSVTextExtractor(AbstractFileTextExtractor):
    @run_in_process
    def _extract(self, content: bytes) -> str:
        text_content = content.decode("utf-8")
        csv_file = StringIO(text_content)
        reader = csv.reader(csv_file)
        extracted_rows = [
            ",".join(r)
            for r in reader
            if r and len(r[0].replace(",", "")) != 0
        ]  # fmt: skip
        return "\n".join(extracted_rows)
