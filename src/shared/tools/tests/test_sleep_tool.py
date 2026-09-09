from unittest.mock import MagicMock

import pytest

from conftest import load_tool_main

sleep_module = load_tool_main("sleep_tool")
sleep_main = sleep_module.main
DEFAULT_MAX_SECONDS = sleep_module.DEFAULT_MAX_SECONDS


@pytest.fixture(autouse=True)
def _reset_config_globals():
    # Ensure no leftover 'max_seconds' global bleeds between tests, mirroring
    # how the sandbox injects tool config as module-level globals.
    sleep_module.__dict__.pop("max_seconds", None)
    yield
    sleep_module.__dict__.pop("max_seconds", None)


@pytest.fixture
def mock_sleep(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(sleep_module.time, "sleep", mock)
    return mock


class TestSleepToolHappyPath:
    def test_sleeps_for_requested_duration_and_reports_reason(self, mock_sleep):
        result = sleep_main(seconds=30, reason="waiting for rate-limit window to reset")

        mock_sleep.assert_called_once_with(30.0)
        assert isinstance(result, str)
        assert "30" in result
        assert "waiting for rate-limit window to reset" in result
        assert not result.startswith("Error")

    def test_default_max_seconds_used_when_not_configured(self, mock_sleep):
        result = sleep_main(seconds=10, reason="brief pause")

        mock_sleep.assert_called_once_with(10.0)
        assert "10" in result

    def test_float_seconds_accepted(self, mock_sleep):
        result = sleep_main(seconds=2.5, reason="short pause")

        mock_sleep.assert_called_once_with(2.5)
        assert "2.5" in result


class TestSleepToolClamping:
    def test_clamped_when_exceeding_configured_max_seconds(self, mock_sleep):
        sleep_module.max_seconds = 60

        result = sleep_main(seconds=120, reason="waiting for a long job")

        mock_sleep.assert_called_once_with(60.0)
        assert "capped" in result.lower()
        assert "120" in result
        assert "60" in result

    def test_not_clamped_when_within_configured_max_seconds(self, mock_sleep):
        sleep_module.max_seconds = 60

        result = sleep_main(seconds=30, reason="short wait")

        mock_sleep.assert_called_once_with(30.0)
        assert "capped" not in result.lower()

    def test_clamped_against_default_max_seconds_when_unconfigured(self, mock_sleep):
        result = sleep_main(seconds=DEFAULT_MAX_SECONDS + 500, reason="very long wait")

        mock_sleep.assert_called_once_with(float(DEFAULT_MAX_SECONDS))
        assert "capped" in result.lower()

    def test_invalid_configured_max_seconds_falls_back_to_default(self, mock_sleep):
        sleep_module.max_seconds = "not-a-number"

        result = sleep_main(seconds=10, reason="pause")

        mock_sleep.assert_called_once_with(10.0)
        assert not result.startswith("Error")

    def test_max_seconds_passed_as_stray_kwarg_is_absorbed_and_global_wins(self, mock_sleep):
        """Regression test (smoke test): python_code.global_kwargs
        folds user_input config (max_seconds) into func_kwargs, so main()
        may also receive it as a kwarg. The global remains the source of
        truth; the stray kwarg must be swallowed by **kwargs without a
        TypeError."""
        sleep_module.max_seconds = 60

        result = sleep_main(seconds=120, reason="stray kwarg test", max_seconds=999)

        mock_sleep.assert_called_once_with(60.0)
        assert "capped" in result.lower()


class TestSleepToolErrorPaths:
    def test_missing_seconds_returns_error_string(self, mock_sleep):
        result = sleep_main(reason="no duration given")

        assert isinstance(result, str)
        assert result.startswith("Error:")
        mock_sleep.assert_not_called()

    def test_zero_seconds_returns_error_string(self, mock_sleep):
        result = sleep_main(seconds=0, reason="zero duration")

        assert result.startswith("Error:")
        mock_sleep.assert_not_called()

    def test_negative_seconds_returns_error_string(self, mock_sleep):
        result = sleep_main(seconds=-5, reason="negative duration")

        assert result.startswith("Error:")
        mock_sleep.assert_not_called()

    def test_non_numeric_seconds_returns_error_string(self, mock_sleep):
        result = sleep_main(seconds="not-a-number", reason="bad type")

        assert result.startswith("Error:")
        mock_sleep.assert_not_called()

    def test_boolean_seconds_rejected(self, mock_sleep):
        result = sleep_main(seconds=True, reason="bool passed as seconds")

        assert result.startswith("Error:")
        mock_sleep.assert_not_called()

    def test_missing_reason_returns_error_string(self, mock_sleep):
        result = sleep_main(seconds=10)

        assert isinstance(result, str)
        assert result.startswith("Error:")
        mock_sleep.assert_not_called()

    def test_blank_reason_returns_error_string(self, mock_sleep):
        result = sleep_main(seconds=10, reason="   ")

        assert result.startswith("Error:")
        mock_sleep.assert_not_called()

    def test_never_raises_on_unexpected_input(self, mock_sleep):
        result = sleep_main(seconds=object(), reason="weird input")

        assert isinstance(result, str)
        assert result.startswith("Error:")
        mock_sleep.assert_not_called()
