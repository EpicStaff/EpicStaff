from application.ports.document_content_reader import AbstractDocumentContentReader
from domain.errors import ContentStorageUnavailableError, DocumentContentMissingError


class FakeDocumentContentReader(AbstractDocumentContentReader):
    """Serves document files from a dict; `unavailable` makes every read fail as an outage."""

    def __init__(self, files: dict[str, bytes] | None = None, *, unavailable: bool = False):
        self.files = files if files is not None else {}
        self.unavailable = unavailable

    async def read(self, content_key: str) -> bytes:
        if self.unavailable:
            raise ContentStorageUnavailableError()
        try:
            return self.files[content_key]
        except KeyError as error:
            raise DocumentContentMissingError(documents=f"'{content_key}'") from error
