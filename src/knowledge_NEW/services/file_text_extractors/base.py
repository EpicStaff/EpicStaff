import abc


class AbstractFileTextExtractor(abc.ABC):
    """Abstract base for extracting text from raw file bytes.

    Subclasses must implement `extract`; it is the only contract a concrete
    extractor has to fulfil.
    """

    @abc.abstractmethod
    async def extract(self, content: bytes) -> str:
        """Return the text extracted from `content`.

        Implementations must return an empty string when the file has no text,
        and raise `FileTextExtractingError` when the content cannot be extracted.

        Args:
            content: Raw file bytes to extract text from.

        Returns:
            The extracted text, or an empty string when the file has no text.
        """
