from __future__ import annotations

from src.shared.models import DocumentErrorCode, format_error_message


class IndexingErrorClassifier:
    @classmethod
    def for_chunking(cls, exc: BaseException) -> tuple[str, str]:
        return DocumentErrorCode.CHUNKING_FAILED.value, cls.format_message(exc)

    @classmethod
    def for_embedding(cls, exc: BaseException) -> tuple[str, str]:
        return DocumentErrorCode.EMBEDDING_FAILED.value, cls.format_message(exc)

    @classmethod
    def format_message(cls, exc: BaseException) -> str:
        return format_error_message(exc)
