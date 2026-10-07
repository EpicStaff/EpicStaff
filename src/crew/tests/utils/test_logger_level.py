import importlib
import sys

import pytest
import settings
from utils import logger as logger_module


@pytest.fixture
def reload_logger_module(monkeypatch):
    """Re-run the module-level sink setup with a patched level, then restore the original sink."""
    original_excepthook = sys.excepthook

    def reload_with_level(level: str):
        monkeypatch.setattr(settings, "LOG_LEVEL", level)
        importlib.reload(logger_module)
        return logger_module.logger

    yield reload_with_level
    monkeypatch.undo()
    importlib.reload(logger_module)
    sys.excepthook = original_excepthook


def test_stdout_sink_drops_records_below_crew_log_level(reload_logger_module, capsys):
    logger = reload_logger_module("WARNING")

    logger.info("info record must be filtered")
    logger.warning("warning record must be written")

    stdout = capsys.readouterr().out
    assert "info record must be filtered" not in stdout
    assert "warning record must be written" in stdout


def test_stdout_sink_writes_debug_records_at_debug_level(reload_logger_module, capsys):
    logger = reload_logger_module("DEBUG")

    logger.debug("debug record must be written")

    assert "debug record must be written" in capsys.readouterr().out
