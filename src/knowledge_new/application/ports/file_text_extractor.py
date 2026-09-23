import abc

from domain.errors import FileTextExtractingError


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
            return await self._extract(content)
        except Exception as e:
            raise FileTextExtractingError(extractor=type(self).__name__) from e

    @abc.abstractmethod
    async def _extract(self, content: bytes) -> str:
        """Return the text extracted from `content`.

        `extract` translates any error into `FileTextExtractingError`, so
        implementations need not wrap exceptions themselves.
        """
