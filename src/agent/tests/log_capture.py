"""Helpers for capturing and asserting on loguru output in tests."""

from __future__ import annotations

import sys
from contextlib import contextmanager

from loguru import logger


@contextmanager
def capture_logs_at(level: str):
    """Capture log messages with `level` as the only active sink's floor.

    Every other sink is removed for the duration, so loguru's lazy formatting is
    skipped for anything below `level` — which is what makes a "nothing is logged"
    assertion meaningful. Restoring a bare stderr sink afterward (rather than saving
    and restoring whatever was there) is safe because this service only configures a
    sink inside `main()`, which no test calls — so the only state to return to is
    loguru's own default, regardless of whether a test module imports `main.py`.
    """
    messages: list[str] = []
    logger.remove()
    sink_id = logger.add(messages.append, level=level, format="{message}")
    try:
        yield messages
    finally:
        logger.remove(sink_id)
        logger.add(sys.stderr)


def log_line_starting_with(messages: list[str], prefix: str) -> str:
    matches = [message for message in messages if message.startswith(prefix)]
    assert len(matches) == 1, f"expected exactly one {prefix!r} line, got {matches}"
    return matches[0].rstrip("\n")


def assert_masked_exception(line: str, exception_class: str) -> None:
    """Assert `line` names `exception_class` but carries only a length and a digest of its message."""
    assert f"{exception_class}: <redacted len=" in line, line
    assert "digest=" in line, line
