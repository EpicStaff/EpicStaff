"""Map indexing exceptions to a persisted (error_code, error_message) pair."""

from enums import DocumentErrorCode
from errors import FileTextExtractingError, ChunkingError, EmbeddingError
from utils import format_error_message


class IndexingErrorClassifier:
    """Classify indexing failures by the phase they occurred in."""

    @classmethod
    def for_chunking(cls, exc: BaseException) -> tuple[DocumentErrorCode, str]:
        return DocumentErrorCode.CHUNKING_FAILED, format_error_message(exc)

    @classmethod
    def for_embedding(cls, exc: BaseException) -> tuple[DocumentErrorCode, str]:
        return DocumentErrorCode.EMBEDDING_FAILED, format_error_message(exc)

    @classmethod
    def for_unknown(cls, exc: BaseException) -> tuple[DocumentErrorCode, str]:
        return DocumentErrorCode.UNKNOWN, format_error_message(exc)

    @classmethod
    def classify(cls, exc: BaseException) -> tuple[DocumentErrorCode, str]:
        if isinstance(exc, (FileTextExtractingError, ChunkingError)):
            return cls.for_chunking(exc)
        if isinstance(exc, EmbeddingError):
            return cls.for_embedding(exc)
        return cls.for_unknown(exc)
