"""The service's log sinks at a given SANDBOX_LOG_LEVEL.

At BENCH (or below) every checkpoint is written once, as one JSON line starting with
`{"bench"` -- whatever reads these lines keeps only that prefix -- and the normal sink does
not print it a second time. At INFO no checkpoint is written.
"""

import json
import logging
import sys

import pytest
from loguru import logger

from common import settings
from common.bootstrap.logging import _drop_seam_access_lines
from common.bootstrap.logging import INTERCEPTED, configure_logging

BENCH_LEVEL = 15


@pytest.fixture
def configure_logging_at(monkeypatch):
    """Run configure_logging at a patched level, then restore loguru and stdlib logging.

    configure_logging replaces every loguru sink and the stdlib root handlers, which other
    tests and pytest's own log capture rely on.
    """
    root = logging.getLogger()
    saved_root = (root.handlers[:], root.level)
    saved_intercepted = {
        name: (logging.getLogger(name).handlers[:], logging.getLogger(name).propagate)
        for name in INTERCEPTED
    }

    def configure(level: str):
        monkeypatch.setattr(settings, "LOG_LEVEL", level)
        configure_logging()

    yield configure

    logger.remove()
    # The capsys stream closes after this test; never leave a sink pointing at it.
    logger.add(sys.__stderr__)
    root.handlers, root.level = saved_root
    for name, (handlers, propagate) in saved_intercepted.items():
        logging.getLogger(name).handlers = handlers
        logging.getLogger(name).propagate = propagate


def test_bench_level_writes_each_checkpoint_once_as_a_json_line(configure_logging_at, capsys):
    configure_logging_at("BENCH")

    logger.log(
        BENCH_LEVEL, "bench {checkpoint}", checkpoint="exec_start", session_id=7, execution_id="e1"
    )
    logger.debug("debug record must be filtered")
    logger.info("info record must be written")

    lines = capsys.readouterr().err.splitlines()
    checkpoints = [json.loads(line) for line in lines if line.startswith('{"bench"')]
    assert [(item["checkpoint"], item["session_id"], item["execution_id"]) for item in checkpoints] == [
        ("exec_start", 7, "e1")
    ]
    assert sum("exec_start" in line for line in lines) == 1
    assert not any("debug record must be filtered" in line for line in lines)
    assert any("info record must be written" in line for line in lines)


def test_info_level_writes_no_checkpoints(configure_logging_at, capsys):
    configure_logging_at("INFO")

    logger.log(BENCH_LEVEL, "bench {checkpoint}", checkpoint="exec_start")

    assert "exec_start" not in capsys.readouterr().err
def access_record(path: str, status: int) -> logging.LogRecord:
    """A record shaped the way uvicorn.access emits them: args = (client, method, path, http, status)."""
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:1", "GET", path, "1.1", status),
        exc_info=None,
    )


def test_successful_seam_access_lines_are_dropped():
    assert _drop_seam_access_lines(access_record("/worker/heartbeat", 204)) is False
    assert _drop_seam_access_lines(access_record("/worker/jobs", 200)) is False


def test_refused_seam_access_lines_are_kept():
    """A 401 on the job endpoints is someone probing for payloads with secrets."""
    assert _drop_seam_access_lines(access_record("/worker/jobs", 401)) is True


def test_other_access_lines_are_kept():
    assert _drop_seam_access_lines(access_record("/executions", 200)) is True
