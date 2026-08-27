import os


DEFAULT_MAX_INPUT_BYTES = 64 * 1024 * 1024  # 64 MB of uploaded file
DEFAULT_MAX_PAGES = 2_000


class ExtractionLimitExceeded(ValueError):
    """Raised when a document costs more to extract than its budget allows."""


class ExtractionBudget:
    """Bounds one extraction in input size and page count."""

    def __init__(self, *, max_input_bytes: int, max_pages: int):
        self.max_input_bytes = max_input_bytes
        self.max_pages = max_pages
        self.pages_seen = 0

    def check_input_size(self, binary_content: bytes) -> None:
        """Reject a file too large to extract before any parser touches it."""
        size = len(binary_content)
        if size > self.max_input_bytes:
            raise ExtractionLimitExceeded(
                f"File is {size} bytes, over the {self.max_input_bytes} bytes "
                "extraction limit"
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
        max_pages=_env_int("KNOWLEDGE_MAX_EXTRACTION_PAGES", DEFAULT_MAX_PAGES),
    )
