from abc import ABC, abstractmethod


class AbstractDocumentContentReader(ABC):
    """Reads the stored bytes of a knowledge document.

    django_app writes and deletes the files; this service only reads them, by the key
    the document's content row holds.
    """

    @abstractmethod
    async def read(self, content_key: str) -> bytes:
        """Return the whole stored file.

        Raises:
            DocumentContentMissingError: Nothing is stored under `content_key`.
            ContentStorageUnavailableError: The storage could not be reached.
        """
