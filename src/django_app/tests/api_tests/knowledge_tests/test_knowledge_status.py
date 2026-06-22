"""Tests for src/shared/models/knowledge_status.py — pure Python, no Django DB."""

import pytest

from src.shared.models.knowledge_status import (
    AGGREGATION_IN_PROGRESS,
    CHUNK_PARAM_FIELDS,
    RACE_GUARD_IN_PROGRESS,
    DocumentStatus,
    RagStatus,
    compute_rag_status,
    format_error_message,
    is_snapshot_current,
    summarize_rag_error,
)


class TestComputeRagStatus:
    def test_empty_list_returns_new(self):
        assert compute_rag_status([]) == RagStatus.NEW.value

    def test_all_new_returns_new(self):
        assert compute_rag_status(["new", "new", "new"]) == RagStatus.NEW.value

    def test_chunking_triggers_processing(self):
        assert compute_rag_status(["new", "chunking"]) == RagStatus.PROCESSING.value

    def test_chunked_triggers_processing(self):
        # CHUNKED is in AGGREGATION_IN_PROGRESS (preview state = in progress for UX)
        assert (
            compute_rag_status(["completed", "chunked"]) == RagStatus.PROCESSING.value
        )

    def test_indexing_triggers_processing(self):
        assert (
            compute_rag_status(["completed", "indexing"]) == RagStatus.PROCESSING.value
        )

    def test_all_completed_returns_completed(self):
        assert (
            compute_rag_status(["completed", "completed"]) == RagStatus.COMPLETED.value
        )

    def test_all_failed_returns_failed(self):
        assert compute_rag_status(["failed", "failed"]) == RagStatus.FAILED.value

    def test_mixed_completed_failed_returns_warning(self):
        assert compute_rag_status(["completed", "failed"]) == RagStatus.WARNING.value

    def test_mixed_completed_warning_returns_warning(self):
        assert compute_rag_status(["completed", "warning"]) == RagStatus.WARNING.value

    def test_single_completed_returns_completed(self):
        assert compute_rag_status(["completed"]) == RagStatus.COMPLETED.value

    def test_in_progress_takes_priority_over_failed(self):
        # PROCESSING is matched before FAILED in rule ordering
        assert compute_rag_status(["failed", "indexing"]) == RagStatus.PROCESSING.value


class TestSummarizeRagError:
    def test_no_problems_returns_none(self):
        assert summarize_rag_error(["completed", "completed"]) is None

    def test_all_new_returns_none(self):
        assert summarize_rag_error(["new"]) is None

    def test_empty_returns_none(self):
        assert summarize_rag_error([]) is None

    def test_one_failed_of_two_returns_message(self):
        result = summarize_rag_error(["completed", "failed"])
        assert result == "1 of 2 document(s) failed or produced warnings."

    def test_one_warning_of_two_returns_message(self):
        result = summarize_rag_error(["completed", "warning"])
        assert result == "1 of 2 document(s) failed or produced warnings."

    def test_all_failed_counts_correctly(self):
        result = summarize_rag_error(["failed", "failed", "failed"])
        assert result == "3 of 3 document(s) failed or produced warnings."

    def test_mixed_failed_and_warning_counts_both(self):
        result = summarize_rag_error(["completed", "failed", "warning"])
        assert result == "2 of 3 document(s) failed or produced warnings."


class TestIsSnapshotCurrent:
    def _live(self, **overrides):
        base = {
            "chunk_size": 1000,
            "chunk_overlap": 150,
            "chunk_strategy": "token",
            "additional_params": {},
        }
        base.update(overrides)
        return base

    def test_identical_mappings_returns_true(self):
        live = self._live()
        assert is_snapshot_current(live, live) is True

    def test_size_mismatch_returns_false(self):
        live = self._live()
        indexed = {**live, "chunk_size": 500}
        assert is_snapshot_current(live, indexed) is False

    def test_overlap_mismatch_returns_false(self):
        live = self._live()
        indexed = {**live, "chunk_overlap": 0}
        assert is_snapshot_current(live, indexed) is False

    def test_strategy_mismatch_returns_false(self):
        live = self._live()
        indexed = {**live, "chunk_strategy": "character"}
        assert is_snapshot_current(live, indexed) is False

    def test_null_snapshot_field_returns_false(self):
        live = self._live()
        indexed = {**live, "chunk_size": None}
        assert is_snapshot_current(live, indexed) is False

    def test_all_nulls_in_indexed_returns_false(self):
        live = self._live()
        indexed = {f: None for f in CHUNK_PARAM_FIELDS}
        assert is_snapshot_current(live, indexed) is False

    def test_additional_params_mismatch_returns_false(self):
        live = self._live(additional_params={"sep": "\n"})
        indexed = self._live(additional_params={})
        assert is_snapshot_current(live, indexed) is False


class TestFormatErrorMessage:
    def test_simple_exception_includes_type_and_text(self):
        exc = ValueError("something went wrong")
        result = format_error_message(exc)
        assert result == "ValueError: something went wrong"

    def test_message_within_limit_not_truncated(self):
        exc = ValueError("short")
        result = format_error_message(exc)
        assert not result.endswith("…")

    def test_long_message_truncated_to_2000_chars(self):
        exc = ValueError("x" * 3000)
        result = format_error_message(exc)
        assert len(result) == 2000
        assert result.endswith("…")

    def test_provider_body_message_preferred(self):
        exc = Exception("raw text")
        exc.body = {"message": "provider says invalid key"}
        result = format_error_message(exc)
        assert result == "provider says invalid key"

    def test_provider_nested_body_error_message(self):
        exc = Exception("raw text")
        exc.body = {"error": {"message": "nested provider error"}}
        result = format_error_message(exc)
        assert result == "nested provider error"

    def test_orig_preferred_over_outer_exc(self):
        """For DB errors, prefers exc.orig to avoid leaking SQL."""
        inner = ValueError("underlying db error")
        outer = Exception("outer with sql and params")
        outer.orig = inner
        result = format_error_message(outer)
        assert "underlying db error" in result
        assert "sql and params" not in result

    def test_no_body_falls_back_to_typename_str(self):
        exc = RuntimeError("plain error")
        result = format_error_message(exc)
        assert result.startswith("RuntimeError:")


class TestStatusSets:
    """Verify the AGGREGATION vs RACE_GUARD frozenset invariants."""

    def test_chunked_in_aggregation_not_in_race_guard(self):
        assert DocumentStatus.CHUNKED.value in AGGREGATION_IN_PROGRESS
        assert DocumentStatus.CHUNKED.value not in RACE_GUARD_IN_PROGRESS

    def test_chunking_in_both_sets(self):
        assert DocumentStatus.CHUNKING.value in AGGREGATION_IN_PROGRESS
        assert DocumentStatus.CHUNKING.value in RACE_GUARD_IN_PROGRESS

    def test_indexing_in_both_sets(self):
        assert DocumentStatus.INDEXING.value in AGGREGATION_IN_PROGRESS
        assert DocumentStatus.INDEXING.value in RACE_GUARD_IN_PROGRESS

    def test_completed_not_in_either_set(self):
        assert DocumentStatus.COMPLETED.value not in AGGREGATION_IN_PROGRESS
        assert DocumentStatus.COMPLETED.value not in RACE_GUARD_IN_PROGRESS

    def test_race_guard_is_subset_of_aggregation(self):
        assert RACE_GUARD_IN_PROGRESS.issubset(AGGREGATION_IN_PROGRESS)
