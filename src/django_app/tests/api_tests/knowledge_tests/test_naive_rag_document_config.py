"""Tests for NaiveRagDocumentConfig model methods and NaiveRagDocumentConfigValidator."""

import pytest

from tables.exceptions import InvalidChunkParametersException
from tables.models.knowledge_models import NaiveRagDocumentConfig
from tables.validators.chunk_parameter_validator import NaiveRagDocumentConfigValidator


# ── Helpers ──────────────────────────────────────────────────────────────────


def _set_snapshot(cfg: NaiveRagDocumentConfig, **overrides) -> None:
    """Populate all indexed_* snapshot fields from live params (optionally override some)."""
    cfg.indexed_chunk_strategy = overrides.get("chunk_strategy", cfg.chunk_strategy)
    cfg.indexed_chunk_size = overrides.get("chunk_size", cfg.chunk_size)
    cfg.indexed_chunk_overlap = overrides.get("chunk_overlap", cfg.chunk_overlap)
    cfg.indexed_additional_params = overrides.get(
        "additional_params", cfg.additional_params
    )


# ── is_snapshot_current ──────────────────────────────────────────────────────


class TestIsSnapshotCurrent:
    @pytest.mark.django_db
    def test_fresh_config_has_no_snapshot(self, naive_rag_document_config):
        assert naive_rag_document_config.is_snapshot_current() is False

    @pytest.mark.django_db
    def test_snapshot_matches_live_returns_true(self, naive_rag_document_config):
        _set_snapshot(naive_rag_document_config)
        assert naive_rag_document_config.is_snapshot_current() is True

    @pytest.mark.django_db
    def test_size_differs_returns_false(self, naive_rag_document_config):
        _set_snapshot(
            naive_rag_document_config,
            chunk_size=naive_rag_document_config.chunk_size + 100,
        )
        assert naive_rag_document_config.is_snapshot_current() is False

    @pytest.mark.django_db
    def test_strategy_differs_returns_false(self, naive_rag_document_config):
        _set_snapshot(naive_rag_document_config, chunk_strategy="character")
        assert naive_rag_document_config.is_snapshot_current() is False


# ── mark_failed ──────────────────────────────────────────────────────────────


class TestMarkFailed:
    @pytest.mark.django_db
    def test_sets_failed_status(self, naive_rag_document_config):
        naive_rag_document_config.mark_failed(
            NaiveRagDocumentConfig.DocumentErrorCode.EMBEDDING_FAILED,
            RuntimeError("embed error"),
        )
        assert (
            naive_rag_document_config.status
            == NaiveRagDocumentConfig.NaiveRagDocumentStatus.FAILED
        )

    @pytest.mark.django_db
    def test_sets_error_code(self, naive_rag_document_config):
        naive_rag_document_config.mark_failed(
            NaiveRagDocumentConfig.DocumentErrorCode.EMBEDDING_FAILED,
            RuntimeError("embed error"),
        )
        assert (
            naive_rag_document_config.error_code
            == NaiveRagDocumentConfig.DocumentErrorCode.EMBEDDING_FAILED
        )

    @pytest.mark.django_db
    def test_sets_error_message(self, naive_rag_document_config):
        naive_rag_document_config.mark_failed(
            NaiveRagDocumentConfig.DocumentErrorCode.EMBEDDING_FAILED,
            RuntimeError("embed error"),
        )
        assert naive_rag_document_config.error_message is not None
        assert "embed error" in naive_rag_document_config.error_message

    @pytest.mark.django_db
    def test_sets_failed_at(self, naive_rag_document_config):
        naive_rag_document_config.mark_failed(
            NaiveRagDocumentConfig.DocumentErrorCode.EMBEDDING_FAILED,
            RuntimeError("embed error"),
        )
        assert naive_rag_document_config.failed_at is not None

    @pytest.mark.django_db
    def test_returns_formatted_message(self, naive_rag_document_config):
        msg = naive_rag_document_config.mark_failed(
            NaiveRagDocumentConfig.DocumentErrorCode.CHUNKING_FAILED,
            RuntimeError("chunk error"),
        )
        assert isinstance(msg, str)
        assert "chunk error" in msg

    @pytest.mark.django_db
    def test_different_error_codes(self, naive_rag_document_config):
        for code in [
            NaiveRagDocumentConfig.DocumentErrorCode.CHUNKING_FAILED,
            NaiveRagDocumentConfig.DocumentErrorCode.EMBEDDER_AUTH,
            NaiveRagDocumentConfig.DocumentErrorCode.EMBEDDER_RATE_LIMIT,
        ]:
            naive_rag_document_config.mark_failed(code, RuntimeError("x"))
            assert naive_rag_document_config.error_code == code


# ── mark_completed ───────────────────────────────────────────────────────────


class TestMarkCompleted:
    @pytest.mark.django_db
    def test_sets_completed_status(self, naive_rag_document_config):
        naive_rag_document_config.mark_completed()
        assert (
            naive_rag_document_config.status
            == NaiveRagDocumentConfig.NaiveRagDocumentStatus.COMPLETED
        )

    @pytest.mark.django_db
    def test_clears_error_fields_after_failure(self, naive_rag_document_config):
        naive_rag_document_config.mark_failed(
            NaiveRagDocumentConfig.DocumentErrorCode.EMBEDDING_FAILED,
            RuntimeError("x"),
        )
        naive_rag_document_config.mark_completed()
        assert naive_rag_document_config.error_message is None
        assert (
            naive_rag_document_config.error_code
            == NaiveRagDocumentConfig.DocumentErrorCode.NONE
        )
        assert naive_rag_document_config.failed_at is None

    @pytest.mark.django_db
    def test_sets_processed_at_when_provided(self, naive_rag_document_config):
        from django.utils import timezone

        ts = timezone.now()
        naive_rag_document_config.mark_completed(processed_at=ts)
        assert naive_rag_document_config.processed_at == ts


# ── start_attempt ────────────────────────────────────────────────────────────


class TestStartAttempt:
    @pytest.mark.django_db
    def test_sets_chunking_status(self, naive_rag_document_config):
        naive_rag_document_config.start_attempt(
            NaiveRagDocumentConfig.NaiveRagDocumentStatus.CHUNKING
        )
        assert (
            naive_rag_document_config.status
            == NaiveRagDocumentConfig.NaiveRagDocumentStatus.CHUNKING
        )

    @pytest.mark.django_db
    def test_sets_indexing_status(self, naive_rag_document_config):
        naive_rag_document_config.start_attempt(
            NaiveRagDocumentConfig.NaiveRagDocumentStatus.INDEXING
        )
        assert (
            naive_rag_document_config.status
            == NaiveRagDocumentConfig.NaiveRagDocumentStatus.INDEXING
        )

    @pytest.mark.django_db
    def test_clears_stale_error_code(self, naive_rag_document_config):
        naive_rag_document_config.mark_failed(
            NaiveRagDocumentConfig.DocumentErrorCode.EMBEDDING_FAILED,
            RuntimeError("x"),
        )
        naive_rag_document_config.start_attempt(
            NaiveRagDocumentConfig.NaiveRagDocumentStatus.INDEXING
        )
        assert (
            naive_rag_document_config.error_code
            == NaiveRagDocumentConfig.DocumentErrorCode.NONE
        )

    @pytest.mark.django_db
    def test_clears_stale_error_message(self, naive_rag_document_config):
        naive_rag_document_config.mark_failed(
            NaiveRagDocumentConfig.DocumentErrorCode.EMBEDDING_FAILED,
            RuntimeError("x"),
        )
        naive_rag_document_config.start_attempt(
            NaiveRagDocumentConfig.NaiveRagDocumentStatus.INDEXING
        )
        assert naive_rag_document_config.error_message is None

    @pytest.mark.django_db
    def test_clears_failed_at(self, naive_rag_document_config):
        naive_rag_document_config.mark_failed(
            NaiveRagDocumentConfig.DocumentErrorCode.EMBEDDING_FAILED,
            RuntimeError("x"),
        )
        naive_rag_document_config.start_attempt(
            NaiveRagDocumentConfig.NaiveRagDocumentStatus.INDEXING
        )
        assert naive_rag_document_config.failed_at is None


# ── apply_param_updates ──────────────────────────────────────────────────────


class TestApplyParamUpdates:
    @pytest.mark.django_db
    def test_no_change_returns_false(self, naive_rag_document_config):
        cfg = naive_rag_document_config
        result = cfg.apply_param_updates({"chunk_size": cfg.chunk_size})
        assert result is False

    @pytest.mark.django_db
    def test_changed_returns_true(self, naive_rag_document_config):
        result = naive_rag_document_config.apply_param_updates({"chunk_size": 500})
        assert result is True

    @pytest.mark.django_db
    def test_mutates_field_in_memory(self, naive_rag_document_config):
        naive_rag_document_config.apply_param_updates({"chunk_size": 500})
        assert naive_rag_document_config.chunk_size == 500

    @pytest.mark.django_db
    def test_status_realigned_to_new_without_snapshot(self, naive_rag_document_config):
        # No indexed snapshot → after param change, status becomes NEW
        naive_rag_document_config.apply_param_updates({"chunk_size": 500})
        assert (
            naive_rag_document_config.status
            == NaiveRagDocumentConfig.NaiveRagDocumentStatus.NEW
        )

    @pytest.mark.django_db
    def test_status_realigned_to_completed_when_snapshot_matches(
        self, naive_rag_document_config
    ):
        cfg = naive_rag_document_config
        # Set snapshot to match the new value we're about to apply
        _set_snapshot(cfg, chunk_size=500)
        cfg.apply_param_updates({"chunk_size": 500})
        assert cfg.status == NaiveRagDocumentConfig.NaiveRagDocumentStatus.COMPLETED

    @pytest.mark.django_db
    def test_no_realignment_while_indexing(self, naive_rag_document_config):
        cfg = naive_rag_document_config
        cfg.status = NaiveRagDocumentConfig.NaiveRagDocumentStatus.INDEXING
        cfg.apply_param_updates({"chunk_size": 500})
        # Must remain INDEXING — active worker, no status change allowed
        assert cfg.status == NaiveRagDocumentConfig.NaiveRagDocumentStatus.INDEXING

    @pytest.mark.django_db
    def test_no_realignment_while_chunking(self, naive_rag_document_config):
        cfg = naive_rag_document_config
        cfg.status = NaiveRagDocumentConfig.NaiveRagDocumentStatus.CHUNKING
        cfg.apply_param_updates({"chunk_size": 500})
        assert cfg.status == NaiveRagDocumentConfig.NaiveRagDocumentStatus.CHUNKING

    @pytest.mark.django_db
    def test_realignment_allowed_while_chunked(self, naive_rag_document_config):
        # CHUNKED = preview-only, no active worker → realignment is allowed
        cfg = naive_rag_document_config
        cfg.status = NaiveRagDocumentConfig.NaiveRagDocumentStatus.CHUNKED
        cfg.apply_param_updates({"chunk_size": 500})
        assert cfg.status != NaiveRagDocumentConfig.NaiveRagDocumentStatus.CHUNKED

    @pytest.mark.django_db
    def test_error_cleared_on_realignment(self, naive_rag_document_config):
        cfg = naive_rag_document_config
        cfg.mark_failed(
            NaiveRagDocumentConfig.DocumentErrorCode.EMBEDDING_FAILED, RuntimeError("x")
        )
        cfg.apply_param_updates({"chunk_size": 500})
        assert cfg.error_message is None
        assert cfg.error_code == NaiveRagDocumentConfig.DocumentErrorCode.NONE


# ── NaiveRagDocumentConfigValidator.allowed_strategies_for_file_type ─────────


class TestAllowedStrategiesForFileType:
    def test_pdf_only_universal(self):
        allowed = NaiveRagDocumentConfigValidator.allowed_strategies_for_file_type(
            "pdf"
        )
        assert "token" in allowed
        assert "character" in allowed
        assert "json" not in allowed
        assert "markdown" not in allowed
        assert "html" not in allowed
        assert "csv" not in allowed

    def test_json_includes_json_strategy(self):
        allowed = NaiveRagDocumentConfigValidator.allowed_strategies_for_file_type(
            "json"
        )
        assert "json" in allowed
        assert "token" in allowed

    def test_md_includes_markdown_strategy(self):
        allowed = NaiveRagDocumentConfigValidator.allowed_strategies_for_file_type("md")
        assert "markdown" in allowed
        assert "token" in allowed

    def test_html_includes_html_strategy(self):
        allowed = NaiveRagDocumentConfigValidator.allowed_strategies_for_file_type(
            "html"
        )
        assert "html" in allowed

    def test_csv_includes_csv_strategy(self):
        allowed = NaiveRagDocumentConfigValidator.allowed_strategies_for_file_type(
            "csv"
        )
        assert "csv" in allowed

    def test_unknown_type_returns_only_universal(self):
        allowed = NaiveRagDocumentConfigValidator.allowed_strategies_for_file_type(
            "xyz"
        )
        assert allowed == {"token", "character"}

    def test_txt_only_universal(self):
        allowed = NaiveRagDocumentConfigValidator.allowed_strategies_for_file_type(
            "txt"
        )
        assert allowed == {"token", "character"}

    def test_docx_only_universal(self):
        allowed = NaiveRagDocumentConfigValidator.allowed_strategies_for_file_type(
            "docx"
        )
        assert allowed == {"token", "character"}


# ── NaiveRagDocumentConfigValidator.is_strategy_allowed ──────────────────────


class TestIsStrategyAllowed:
    def test_token_allowed_for_all_types(self):
        for ft in ("pdf", "csv", "json", "md", "html", "txt", "docx"):
            assert NaiveRagDocumentConfigValidator.is_strategy_allowed("token", ft)

    def test_character_allowed_for_all_types(self):
        for ft in ("pdf", "csv", "json", "md", "html"):
            assert NaiveRagDocumentConfigValidator.is_strategy_allowed("character", ft)

    def test_json_not_allowed_for_pdf(self):
        assert not NaiveRagDocumentConfigValidator.is_strategy_allowed("json", "pdf")

    def test_json_allowed_for_json(self):
        assert NaiveRagDocumentConfigValidator.is_strategy_allowed("json", "json")

    def test_markdown_allowed_for_md(self):
        assert NaiveRagDocumentConfigValidator.is_strategy_allowed("markdown", "md")

    def test_markdown_not_allowed_for_pdf(self):
        assert not NaiveRagDocumentConfigValidator.is_strategy_allowed(
            "markdown", "pdf"
        )

    def test_html_allowed_for_html(self):
        assert NaiveRagDocumentConfigValidator.is_strategy_allowed("html", "html")

    def test_csv_allowed_for_csv(self):
        assert NaiveRagDocumentConfigValidator.is_strategy_allowed("csv", "csv")


# ── NaiveRagDocumentConfigValidator.build_updates ────────────────────────────


class TestBuildUpdates:
    def test_filters_none_values(self):
        result = NaiveRagDocumentConfigValidator.build_updates(
            chunk_size=500,
            chunk_overlap=None,
            chunk_strategy=None,
            additional_params=None,
        )
        assert result == {"chunk_size": 500}

    def test_all_provided_included(self):
        result = NaiveRagDocumentConfigValidator.build_updates(
            chunk_size=500,
            chunk_overlap=50,
            chunk_strategy="token",
            additional_params={},
        )
        assert set(result.keys()) == {
            "chunk_size",
            "chunk_overlap",
            "chunk_strategy",
            "additional_params",
        }

    def test_all_none_returns_empty_dict(self):
        result = NaiveRagDocumentConfigValidator.build_updates(None, None, None, None)
        assert result == {}

    def test_zero_overlap_included(self):
        # 0 is a valid value (not None), must not be filtered
        result = NaiveRagDocumentConfigValidator.build_updates(
            chunk_size=None,
            chunk_overlap=0,
            chunk_strategy=None,
            additional_params=None,
        )
        assert result == {"chunk_overlap": 0}


# ── NaiveRagDocumentConfigValidator.collect_errors ───────────────────────────


class TestCollectErrors:
    @pytest.mark.django_db
    def test_valid_update_returns_no_errors(self, naive_rag_document_config):
        errors = NaiveRagDocumentConfigValidator.collect_errors(
            naive_rag_document_config, {"chunk_size": 500, "chunk_overlap": 50}
        )
        assert errors == []

    @pytest.mark.django_db
    def test_chunk_size_too_small_returns_error(self, naive_rag_document_config):
        errors = NaiveRagDocumentConfigValidator.collect_errors(
            naive_rag_document_config,
            {"chunk_size": 1},  # below MIN_CHUNK_SIZE = 20
        )
        assert len(errors) >= 1
        assert any(e["field"] == "chunk_size" for e in errors)

    @pytest.mark.django_db
    def test_chunk_size_too_large_returns_error(self, naive_rag_document_config):
        errors = NaiveRagDocumentConfigValidator.collect_errors(
            naive_rag_document_config,
            {"chunk_size": 99999},  # above MAX_CHUNK_SIZE = 8000
        )
        assert any(e["field"] == "chunk_size" for e in errors)

    @pytest.mark.django_db
    def test_overlap_equal_to_size_returns_error(self, naive_rag_document_config):
        errors = NaiveRagDocumentConfigValidator.collect_errors(
            naive_rag_document_config, {"chunk_size": 100, "chunk_overlap": 100}
        )
        assert any(e["field"] == "chunk_overlap" for e in errors)

    @pytest.mark.django_db
    def test_overlap_greater_than_size_returns_error(self, naive_rag_document_config):
        errors = NaiveRagDocumentConfigValidator.collect_errors(
            naive_rag_document_config, {"chunk_size": 100, "chunk_overlap": 200}
        )
        assert any(e["field"] == "chunk_overlap" for e in errors)

    @pytest.mark.django_db
    def test_strategy_wrong_for_file_type_returns_error(
        self, naive_rag_document_config
    ):
        # fixture document is .pdf → json strategy not allowed
        errors = NaiveRagDocumentConfigValidator.collect_errors(
            naive_rag_document_config, {"chunk_strategy": "json"}
        )
        assert len(errors) == 1
        assert errors[0]["field"] == "chunk_strategy"

    @pytest.mark.django_db
    def test_unknown_strategy_returns_error(self, naive_rag_document_config):
        errors = NaiveRagDocumentConfigValidator.collect_errors(
            naive_rag_document_config, {"chunk_strategy": "nonexistent"}
        )
        assert any(e["field"] == "chunk_strategy" for e in errors)

    @pytest.mark.django_db
    def test_error_dict_has_required_keys(self, naive_rag_document_config):
        errors = NaiveRagDocumentConfigValidator.collect_errors(
            naive_rag_document_config, {"chunk_size": 1}
        )
        assert len(errors) >= 1
        assert {"field", "value", "reason"} <= errors[0].keys()


# ── NaiveRagDocumentConfigValidator.validate_or_raise ────────────────────────


class TestValidateOrRaise:
    @pytest.mark.django_db
    def test_valid_update_does_not_raise(self, naive_rag_document_config):
        NaiveRagDocumentConfigValidator.validate_or_raise(
            naive_rag_document_config, {"chunk_size": 500}
        )

    @pytest.mark.django_db
    def test_invalid_size_raises(self, naive_rag_document_config):
        with pytest.raises(InvalidChunkParametersException):
            NaiveRagDocumentConfigValidator.validate_or_raise(
                naive_rag_document_config, {"chunk_size": 1}
            )

    @pytest.mark.django_db
    def test_overlap_ge_size_raises(self, naive_rag_document_config):
        with pytest.raises(InvalidChunkParametersException):
            NaiveRagDocumentConfigValidator.validate_or_raise(
                naive_rag_document_config, {"chunk_size": 100, "chunk_overlap": 100}
            )
