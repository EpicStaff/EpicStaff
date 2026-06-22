"""Tests for IndexingErrorClassifier (src/knowledge/utils/indexing_error_classifier.py).

The classifier is pure Python (no Django DB required).
"""

import pytest

from src.knowledge.utils.indexing_error_classifier import IndexingErrorClassifier
from src.shared.models.knowledge_status import (
    DocumentErrorCode,
    ERROR_MESSAGE_MAX_LENGTH,
)


class TestForChunking:
    def test_returns_chunking_failed_code(self):
        code, _ = IndexingErrorClassifier.for_chunking(RuntimeError("parse error"))
        assert code == DocumentErrorCode.CHUNKING_FAILED.value

    def test_returns_formatted_message(self):
        _, msg = IndexingErrorClassifier.for_chunking(RuntimeError("parse error"))
        assert "parse error" in msg

    def test_message_is_string(self):
        _, msg = IndexingErrorClassifier.for_chunking(ValueError("bad input"))
        assert isinstance(msg, str)

    def test_returns_two_element_tuple(self):
        result = IndexingErrorClassifier.for_chunking(RuntimeError("x"))
        assert len(result) == 2


class TestForEmbedding:
    def test_returns_embedding_failed_code(self):
        code, _ = IndexingErrorClassifier.for_embedding(RuntimeError("embed error"))
        assert code == DocumentErrorCode.EMBEDDING_FAILED.value

    def test_returns_formatted_message(self):
        _, msg = IndexingErrorClassifier.for_embedding(RuntimeError("embed error"))
        assert "embed error" in msg

    def test_different_from_chunking_code(self):
        chunk_code, _ = IndexingErrorClassifier.for_chunking(RuntimeError("x"))
        embed_code, _ = IndexingErrorClassifier.for_embedding(RuntimeError("x"))
        assert chunk_code != embed_code


class TestFormatMessage:
    def test_includes_exception_text(self):
        exc = RuntimeError("something broke")
        msg = IndexingErrorClassifier.format_message(exc)
        assert "something broke" in msg

    def test_truncates_long_exception(self):
        exc = RuntimeError("x" * 3000)
        msg = IndexingErrorClassifier.format_message(exc)
        assert len(msg) == ERROR_MESSAGE_MAX_LENGTH
        assert msg.endswith("…")

    def test_short_message_not_truncated(self):
        exc = RuntimeError("short")
        msg = IndexingErrorClassifier.format_message(exc)
        assert not msg.endswith("…")

    def test_provider_body_message_extracted(self):
        exc = Exception("raw")
        exc.body = {"message": "Invalid API key provided"}
        msg = IndexingErrorClassifier.format_message(exc)
        assert msg == "Invalid API key provided"
