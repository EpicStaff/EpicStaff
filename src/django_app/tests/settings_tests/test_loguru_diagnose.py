"""The stdout sink configured by `utils.logger` must not print variable values in tracebacks.

With loguru's `diagnose` on, `logger.exception` annotates every variable on the failing lines
with its value, which writes secrets and request payloads into the logs.
"""

import importlib
import sys

import pytest

from utils import logger as logger_module

# Same reason as test_loguru_level.py: without a db-marked test the session-scoped autouse
# flush fixture targets the real dev database.
pytestmark = pytest.mark.django_db

SECRET_VALUE = "sk-diagnose-test-SECRET-value"


@pytest.fixture
def reload_logger_module():
    """Re-run the module-level sink setup, then restore the original sink.

    The reload has to run inside the test body: `capsys` swaps `sys.stdout` only for the call
    phase, and the sink binds to whatever `sys.stdout` is when it is added.
    """
    original_excepthook = sys.excepthook

    def reload():
        importlib.reload(logger_module)
        return logger_module.logger

    yield reload
    importlib.reload(logger_module)
    sys.excepthook = original_excepthook


def _fail_with_secret_in_scope():
    payload = {"token": SECRET_VALUE}
    return payload["missing_key"]


# Keep `reload_logger_module` before `capsys`: fixtures tear down in reverse, so `capsys`
# restores the real stdout before the teardown reload rebinds the sink to it.
def test_exception_traceback_omits_local_variable_values(reload_logger_module, capsys):
    logger = reload_logger_module()

    try:
        _fail_with_secret_in_scope()
    except KeyError:
        logger.exception("lookup failed")

    stdout = capsys.readouterr().out
    assert "lookup failed" in stdout
    assert "KeyError: 'missing_key'" in stdout
    assert 'payload["missing_key"]' in stdout
    assert SECRET_VALUE not in stdout
