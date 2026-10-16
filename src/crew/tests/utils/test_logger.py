import os
import subprocess
import sys
from pathlib import Path

import pytest

CREW_DIR = Path(__file__).resolve().parents[2]

# The sink is configured when utils.logger is first imported, so each case
# starts a fresh interpreter, the same way crew starts.
PROBE = (
    "from utils.logger import logger; "
    "logger.debug('probe-debug'); "
    "logger.info('probe-info'); "
    "logger.warning('probe-warning')"
)


def _start_crew_logger(log_level: str) -> subprocess.CompletedProcess:
    environment = {
        **os.environ,
        "CREW_LOG_LEVEL": log_level,
        "PYTHONPATH": os.pathsep.join(sys.path),
    }
    return subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=CREW_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize(
    ("log_level", "expected_probes"),
    [
        ("INFO", ["probe-info", "probe-warning"]),
        ("debug", ["probe-debug", "probe-info", "probe-warning"]),
        ("Warning", ["probe-warning"]),
    ],
)
def test_crew_log_level_selects_which_messages_are_written(log_level, expected_probes):
    result = _start_crew_logger(log_level)

    assert result.returncode == 0, result.stderr
    written = [
        probe
        for probe in ("probe-debug", "probe-info", "probe-warning")
        if probe in result.stdout
    ]
    assert written == expected_probes


@pytest.mark.parametrize("log_level", ["verbose", "none", ""])
def test_unknown_crew_log_level_stops_startup_naming_the_variable(log_level):
    result = _start_crew_logger(log_level)

    assert result.returncode != 0
    assert "CREW_LOG_LEVEL=" in result.stderr
    assert "is not a log level" in result.stderr
