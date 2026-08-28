import io
import os
import zipfile


_CHUNK_BYTES = 1024 * 1024

DEFAULT_MAX_INPUT_BYTES = 64 * 1024 * 1024  # 64 MB of uploaded file
DEFAULT_MAX_UNPACKED_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_CONTENT_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_HTML_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_PAGES = 2_000


class ExtractionLimitExceeded(ValueError):
    """Raised when a document costs more to extract than its budget allows."""


class ExtractionBudget:
    """Bounds one extraction in input size, unpacked size and page count."""

    def __init__(
        self,
        *,
        max_input_bytes: int,
        max_unpacked_bytes: int,
        max_content_bytes: int,
        max_html_bytes: int,
        max_pages: int,
    ):
        self.max_input_bytes = max_input_bytes
        self.max_unpacked_bytes = max_unpacked_bytes
        self.max_content_bytes = max_content_bytes
        self.max_html_bytes = max_html_bytes
        self.max_pages = max_pages
        self.pages_seen = 0
        self.content_bytes_seen = 0

    def check_input_size(self, binary_content: bytes) -> None:
        """Reject a file too large to extract before any parser touches it."""
        size = len(binary_content)
        if size > self.max_input_bytes:
            raise ExtractionLimitExceeded(
                f"File is {size} bytes, over the {self.max_input_bytes} bytes "
                "extraction limit"
            )

    def check_unpacked_size(self, binary_content: bytes) -> None:
        """Reject a container document that unpacks to more data than allowed."""
        buffer = io.BytesIO(binary_content)
        if not zipfile.is_zipfile(buffer):
            return

        buffer.seek(0)
        total = 0
        try:
            with zipfile.ZipFile(buffer) as archive:
                for entry in archive.infolist():
                    # Declared sizes are attacker-controlled, so inflate and
                    # count instead. Raising file_size first stops zipfile
                    # truncating the read back to the declared lie.
                    entry.file_size = self.max_unpacked_bytes - total + 1
                    # A bounded read stops mid-stream, which would trip
                    # zipfile's CRC check; Document() still verifies it later.
                    entry.CRC = None
                    with archive.open(entry) as member:
                        while chunk := member.read(_CHUNK_BYTES):
                            total += len(chunk)
                            if total > self.max_unpacked_bytes:
                                raise ExtractionLimitExceeded(
                                    f"Document unpacks to more than "
                                    f"{self.max_unpacked_bytes} bytes"
                                )
        except zipfile.BadZipFile:
            return

    def check_html_size(self, binary_content: bytes) -> None:
        """Reject HTML too large to build a parse tree for."""
        size = len(binary_content)
        if size > self.max_html_bytes:
            raise ExtractionLimitExceeded(
                f"HTML is {size} bytes, over the {self.max_html_bytes} bytes "
                "extraction limit"
            )

    def add_content_bytes(self, count: int) -> None:
        """Account decoded page content, rejecting a document that decodes too much."""
        self.content_bytes_seen += count
        if self.content_bytes_seen > self.max_content_bytes:
            raise ExtractionLimitExceeded(
                f"Document content decodes to more than {self.max_content_bytes} bytes"
            )

    def count_page(self) -> None:
        """Account one page of work, rejecting a document with too many pages."""
        self.pages_seen += 1
        if self.pages_seen > self.max_pages:
            raise ExtractionLimitExceeded(
                f"Document has more than {self.max_pages} pages"
            )


def _env_int(name: str, default: int) -> int:
    """Read a positive int from the environment, falling back to default."""
    try:
        value = int(os.environ[name])
    except (KeyError, ValueError):
        return default
    return value if value > 0 else default


def default_budget() -> ExtractionBudget:
    """Build the budget applied to extractions that do not supply one."""
    return ExtractionBudget(
        max_input_bytes=_env_int(
            "KNOWLEDGE_MAX_EXTRACTION_INPUT_BYTES", DEFAULT_MAX_INPUT_BYTES
        ),
        max_unpacked_bytes=_env_int(
            "KNOWLEDGE_MAX_EXTRACTION_UNPACKED_BYTES", DEFAULT_MAX_UNPACKED_BYTES
        ),
        max_content_bytes=_env_int(
            "KNOWLEDGE_MAX_EXTRACTION_CONTENT_BYTES", DEFAULT_MAX_CONTENT_BYTES
        ),
        max_html_bytes=_env_int(
            "KNOWLEDGE_MAX_EXTRACTION_HTML_BYTES", DEFAULT_MAX_HTML_BYTES
        ),
        max_pages=_env_int("KNOWLEDGE_MAX_EXTRACTION_PAGES", DEFAULT_MAX_PAGES),
    )
