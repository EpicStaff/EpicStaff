import os
import time
from typing import Callable


DEFAULT_MAX_INPUT_BYTES = 64 * 1024 * 1024  # 64 MB of uploaded file
DEFAULT_MAX_PAGES = 2_000
DEFAULT_MAX_CHARS = 20_000_000  # ~20 MB of extracted text
DEFAULT_MAX_SECONDS = 120.0


class ExtractionLimitExceeded(ValueError):
    """Raised when a document costs more to extract than its budget allows."""


class ExtractionBudget:
    """Bounds one extraction in input size, page count, output size and wall-clock time."""

    def __init__(
        self,
        *,
        max_input_bytes: int,
        max_pages: int,
        max_chars: int,
        max_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.max_input_bytes = max_input_bytes
        self.max_pages = max_pages
        self.max_chars = max_chars
        self.max_seconds = max_seconds
        self.pages_seen = 0
        self.chars_emitted = 0
        self._clock = clock
        self._started_at = clock()

    def check_input_size(self, binary_content: bytes) -> None:
        """Reject a file too large to extract before any parser touches it."""
        size = len(binary_content)
        if size > self.max_input_bytes:
            raise ExtractionLimitExceeded(
                f"File is {size} bytes, over the {self.max_input_bytes} bytes "
                "extraction limit"
            )

    def checkpoint(self) -> None:
        """Reject an extraction that has outrun its wall-clock allowance."""
        elapsed = self._clock() - self._started_at
        if elapsed > self.max_seconds:
            raise ExtractionLimitExceeded(
                f"Text extraction exceeded its limit of {self.max_seconds} seconds"
            )

    def count_page(self) -> None:
        """Account one page of work, rejecting a document with too many pages."""
        self.checkpoint()
        self.pages_seen += 1
        if self.pages_seen > self.max_pages:
            raise ExtractionLimitExceeded(
                f"Document has more than {self.max_pages} pages"
            )

    def add_text(self, text: str) -> None:
        """Account extracted text, rejecting output that outgrows the character cap."""
        self.chars_emitted += len(text)
        if self.chars_emitted > self.max_chars:
            raise ExtractionLimitExceeded(
                f"Extracted text exceeds the {self.max_chars} character limit"
            )


def _env_int(name: str, default: int) -> int:
    """Read a positive int from the environment, falling back to default."""
    try:
        value = int(os.environ[name])
    except (KeyError, ValueError):
        return default
    return value if value > 0 else default


def _env_float(name: str, default: float) -> float:
    """Read a positive float from the environment, falling back to default."""
    try:
        value = float(os.environ[name])
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
        max_chars=_env_int("KNOWLEDGE_MAX_EXTRACTION_CHARS", DEFAULT_MAX_CHARS),
        max_seconds=_env_float("KNOWLEDGE_MAX_EXTRACTION_SECONDS", DEFAULT_MAX_SECONDS),
    )
