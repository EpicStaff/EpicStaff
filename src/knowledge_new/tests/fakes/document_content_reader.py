from application.ports.document_content_reader import AbstractDocumentContentReader
from domain.errors import ContentStorageUnavailableError, DocumentContentMissingError


class FakeDocumentContentReader(AbstractDocumentContentReader):
    """Serves document files from a dict; `unavailable` makes every read fail as an outage.

    `events`, when given, gets `"read"` for every read, to check its order against the
    unit of work's.
    """

    def __init__(
        self,
        files: dict[str, bytes] | None = None,
        *,
        unavailable: bool = False,
        events: list | None = None,
    ):
        self.files = files if files is not None else {}
        self.unavailable = unavailable
        self.events = events

    async def read(self, content_key: str) -> bytes:
        if self.events is not None:
            self.events.append("read")
        if self.unavailable:
            raise ContentStorageUnavailableError()
        try:
            return self.files[content_key]
        except KeyError as error:
            raise DocumentContentMissingError(documents=f"'{content_key}'") from error
