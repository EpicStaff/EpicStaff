"""process_rag_indexing must record NaiveRag.status = "failed" when embedder
construction fails.

The `_get_cached_embedder(...)` call used to sit BEFORE process_rag_indexing's
own try/except block. Since EmbedderConfigurationError (EST-3696) now raises
instead of silently falling back to a default embedder, a construction failure
at that call site used to escape uncaught -- NaiveRag.status was never set to
"failed", defeating the point of raising loudly in the first place. It must be
caught by the method's own except-block, exactly like any other indexing
failure.
"""

from unittest.mock import MagicMock, patch

from rag.naive_rag_strategy import EmbedderConfigurationError, NaiveRAGStrategy


def test_embedder_construction_failure_marks_rag_failed():
    strategy = NaiveRAGStrategy()

    mock_uow_ctx = MagicMock()
    mock_uow_instance = MagicMock()
    mock_uow_instance.start.return_value.__enter__.return_value = mock_uow_ctx
    mock_uow_instance.start.return_value.__exit__.return_value = False

    with patch(
        "rag.naive_rag_strategy.UnitOfWork", return_value=mock_uow_instance
    ), patch.object(
        strategy,
        "_get_cached_embedder",
        side_effect=EmbedderConfigurationError("boom"),
    ):
        strategy.process_rag_indexing(rag_id=42)

    mock_uow_ctx.naive_rag_storage.update_rag_status.assert_called_once_with(
        naive_rag_id=42, status="failed"
    )
