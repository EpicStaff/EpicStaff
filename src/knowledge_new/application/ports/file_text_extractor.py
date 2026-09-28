import abc

from domain.errors import FileTextExtractingError
from loguru import logger


class AbstractFileTextExtractor(abc.ABC):
    """Abstract base for extracting text from file content."""

    async def extract(self, content: bytes) -> str:
        """Extract text from `content`, translating failures.

        Args:
            content: The raw file bytes to extract text from.

        Raises:
            FileTextExtractingError: If extraction fails for any reason.
        """
        try:
            return self._sanitize(await self._extract(content))
        except Exception as e:
            raise FileTextExtractingError(extractor=type(self).__name__) from e

    def _sanitize(self, text: str) -> str:
        """Hook applied to every extracted text before it is returned.

        Removes NUL characters, which PostgreSQL text columns reject. Subclasses
        extending the hook should call `super()._sanitize(text)`.
        """
        nul_count = text.count("\x00")
        if nul_count:
            logger.warning(
                "{} removed {} NUL characters from extracted text; "
                "the file may be binary or in an unsupported encoding.",
                type(self).__name__,
                nul_count,
            )
            return text.replace("\x00", "")
        return text

    @abc.abstractmethod
    async def _extract(self, content: bytes) -> str:
        """Return the text extracted from `content`.

        `extract` translates any error into `FileTextExtractingError`, so
        implementations need not wrap exceptions themselves.
        """
