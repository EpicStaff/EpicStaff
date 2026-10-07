import importlib
import sys

import pytest
from django.test import override_settings

from utils import logger as logger_module

# Same reason as test_required_signing_keys.py: without a db-marked test the session-scoped
# autouse flush fixture targets the real dev database.
pytestmark = pytest.mark.django_db


@pytest.fixture
def reload_logger_module():
    """Re-run the module-level sink setup under a patched LOG_LEVEL, then restore the original sink."""
    original_excepthook = sys.excepthook
    overrides = []

    def reload_with_level(level: str):
        override = override_settings(LOG_LEVEL=level)
        override.enable()
        overrides.append(override)
        importlib.reload(logger_module)
        return logger_module.logger

    yield reload_with_level
    for override in reversed(overrides):
        override.disable()
    importlib.reload(logger_module)
    sys.excepthook = original_excepthook


def test_stdout_sink_drops_records_below_django_log_level(reload_logger_module, capsys):
    logger = reload_logger_module("WARNING")

    logger.info("info record must be filtered")
    logger.warning("warning record must be written")

    stdout = capsys.readouterr().out
    assert "info record must be filtered" not in stdout
    assert "warning record must be written" in stdout


def test_notset_writes_every_record(reload_logger_module, capsys):
    logger = reload_logger_module("NOTSET")

    logger.trace("trace record must be written")

    assert "trace record must be written" in capsys.readouterr().out


def test_stdout_sink_still_truncates_long_messages(reload_logger_module, capsys):
    logger = reload_logger_module("DEBUG")

    logger.debug("x" * (logger_module.MAX_LOG_LENGTH + 50))

    stdout = capsys.readouterr().out
    assert "x" * logger_module.MAX_LOG_LENGTH + "..." in stdout
    assert "x" * (logger_module.MAX_LOG_LENGTH + 1) not in stdout
