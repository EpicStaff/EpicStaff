import json
import importlib

import pytest
import settings
from utils import logger as logger_module


@pytest.fixture
def reload_logger_module(monkeypatch):
    """Re-run the module-level sink setup with a patched level, then restore the original sink."""

    def reload_with_level(level: str):
        monkeypatch.setattr(settings, "LOG_LEVEL", level)
        importlib.reload(logger_module)
        return logger_module.logger

    yield reload_with_level
    monkeypatch.undo()
    importlib.reload(logger_module)


def test_stdout_sink_drops_records_below_sandbox_log_level(reload_logger_module, capsys):
    logger = reload_logger_module("WARNING")

    logger.info("info record must be filtered")
    logger.warning("warning record must be written")

    stdout = capsys.readouterr().out
    assert "info record must be filtered" not in stdout
    assert "warning record must be written" in stdout


def test_stdout_sink_still_truncates_long_messages(reload_logger_module, capsys):
    logger = reload_logger_module("DEBUG")

    logger.debug("x" * (logger_module.MAX_LOG_LENGTH + 50))

    stdout = capsys.readouterr().out
    assert "x" * logger_module.MAX_LOG_LENGTH + "..." in stdout
    assert "x" * (logger_module.MAX_LOG_LENGTH + 1) not in stdout


def test_bench_level_writes_each_checkpoint_once_as_json(reload_logger_module, capsys):
    logger = reload_logger_module("BENCH")

    logger.log(15, "bench {checkpoint}", checkpoint="slot_acquired", session_id=3)
    logger.debug("debug record must be filtered")
    logger.info("info record must be written")

    lines = capsys.readouterr().out.splitlines()
    checkpoints = [json.loads(line) for line in lines if line.startswith('{"bench"')]
    assert [(item["checkpoint"], item["session_id"]) for item in checkpoints] == [("slot_acquired", 3)]
    assert sum("slot_acquired" in line for line in lines) == 1
    assert not any("debug record must be filtered" in line for line in lines)
    assert any("info record must be written" in line for line in lines)


def test_info_level_writes_no_checkpoints(reload_logger_module, capsys):
    logger = reload_logger_module("INFO")

    logger.log(15, "bench {checkpoint}", checkpoint="slot_acquired")

    assert capsys.readouterr().out == ""
