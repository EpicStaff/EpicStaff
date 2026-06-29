"""Map indexing exceptions to a persisted (error_code, error_message) pair."""

from enums import DocumentErrorCode
from errors import (
    FileTextExtractingError,
    ChunkingError,
    EmbeddingError,
    NoPreviewChunksProducedError,
)
from utils import format_error_message


class IndexingErrorClassifier:
    """Classify indexing failures by the phase they occurred in."""

    @classmethod
    def classify(cls, exc: BaseException) -> tuple[DocumentErrorCode, str]:
        if isinstance(exc, (FileTextExtractingError, ChunkingError, NoPreviewChunksProducedError)):
            error_code = DocumentErrorCode.CHUNKING_FAILED
        elif isinstance(exc, EmbeddingError):
            error_code = DocumentErrorCode.EMBEDDING_FAILED
        else:
            error_code = DocumentErrorCode.UNKNOWN

        return error_code, format_error_message(exc)
