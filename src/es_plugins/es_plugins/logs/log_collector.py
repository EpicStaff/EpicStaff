"""A plugin's output: its log file, the agent's stdout, and the tail sent when it fails.

The plugin's stdout and stderr are a pipe the agent created and handed to the launcher, so
reading and storing them happens here, unprivileged. Accepted lines go to
`logs/<id>/current.log` (rotated at 10 MB, three files kept) and to the agent's stdout as
`[<id>] <line>`, which is where `docker logs es_plugins` shows it.

A plugin cannot flood the node: a per-plugin rate budget (lines and bytes per second) drops
output over the limit and records how much, and the file writes happen off the event loop, so
one noisy plugin cannot block the agent or fill the disk faster than the budget allows.
"""

import asyncio
import os
import sys
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from src.shared.models.plugin_nodes import MAX_LOG_LINE_LENGTH, MAX_LOG_TAIL_LINES

LOG_FILE_NAME = "current.log"
MAX_LOG_FILE_BYTES = 10 * 1024 * 1024
KEPT_LOG_FILES = 3
# A longer line is cut into pieces of this size, so one line cannot fill the agent's memory.
MAX_LINE_BYTES = 64 * 1024
_READ_BYTES = 64 * 1024
# The per-plugin budget: output above it is dropped and counted.
MAX_LINES_PER_SECOND = 500
MAX_BYTES_PER_SECOND = 1024 * 1024


class RotatingLogFile:
    """`current.log`, moved to `current.log.1` (and `.1` to `.2`) when it reaches the cap."""

    def __init__(
        self,
        directory: Path,
        *,
        max_bytes: int = MAX_LOG_FILE_BYTES,
        kept_files: int = KEPT_LOG_FILES,
    ):
        self._directory = directory
        self._max_bytes = max_bytes
        self._kept_files = kept_files
        self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Open for the collector's whole life, across writes; `close` closes it.
        self._file = open(self._path(0), "ab")  # noqa: SIM115
        self._size = self._file.tell()

    def write_lines(self, lines: list[bytes]) -> None:
        """Append `lines` (each gets a newline), rotating as the cap is reached. Call off the loop."""
        for line in lines:
            record = line + b"\n"
            if self._size and self._size + len(record) > self._max_bytes:
                self._rotate()
            self._file.write(record)
            self._size += len(record)
        self._file.flush()

    def close(self) -> None:
        self._file.close()

    def _path(self, index: int) -> Path:
        return self._directory / (LOG_FILE_NAME if index == 0 else f"{LOG_FILE_NAME}.{index}")

    def _rotate(self) -> None:
        self._file.close()
        for index in range(self._kept_files - 1, 0, -1):
            older = self._path(index - 1)
            if older.exists():
                os.replace(older, self._path(index))
        self._file = open(self._path(0), "ab")  # noqa: SIM115
        self._size = 0


class _RateBudget:
    """A one-second token bucket for lines and bytes; `allow` says whether a line fits."""

    def __init__(
        self,
        lines_per_second: int,
        bytes_per_second: int,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._lines_per_second = lines_per_second
        self._bytes_per_second = bytes_per_second
        self._clock = clock
        self._window = clock()
        self._lines = lines_per_second
        self._bytes = bytes_per_second

    def allow(self, size: int) -> bool:
        now = self._clock()
        if now - self._window >= 1.0:
            self._window = now
            self._lines = self._lines_per_second
            self._bytes = self._bytes_per_second
        if self._lines <= 0 or self._bytes < size:
            return False
        self._lines -= 1
        self._bytes -= size
        return True


class LogCollector:
    """Collects one plugin's output across its restarts (the tail survives a restart)."""

    def __init__(
        self,
        identifier: str,
        log_file: RotatingLogFile,
        echo: TextIO = sys.stdout,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._identifier = identifier
        self._log_file = log_file
        self._echo = echo
        self._tail: deque[str] = deque(maxlen=MAX_LOG_TAIL_LINES)
        self._budget = _RateBudget(MAX_LINES_PER_SECOND, MAX_BYTES_PER_SECOND, clock=clock)
        self._dropped = 0

    @property
    def tail(self) -> list[str]:
        return list(self._tail)

    async def collect(self, read_descriptor: int) -> None:
        """Read the pipe until every writer has closed it; the descriptor is closed after."""
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=MAX_LINE_BYTES)
        pipe = os.fdopen(read_descriptor, "rb", buffering=0)
        transport, _ = await loop.connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader), pipe
        )
        pending = b""
        try:
            while chunk := await reader.read(_READ_BYTES):
                pending += chunk
                *lines, pending = pending.split(b"\n")
                while len(pending) > MAX_LINE_BYTES:
                    lines.append(pending[:MAX_LINE_BYTES])
                    pending = pending[MAX_LINE_BYTES:]
                await self._record(lines)
            if pending:
                await self._record([pending])
            if self._dropped:
                # The process has closed its output: say what was dropped now, not at its next line.
                await asyncio.to_thread(self._write, [self._dropped_notice()])
                self._dropped = 0
        finally:
            transport.close()

    async def _record(self, raw_lines: list[bytes]) -> None:
        accepted: list[bytes] = []
        for raw_line in raw_lines:
            line = raw_line.rstrip(b"\r")
            if not self._budget.allow(len(line)):
                self._dropped += 1
                continue
            if self._dropped:
                accepted.append(self._dropped_notice())
                self._dropped = 0
            accepted.append(line)
            self._tail.append(line.decode("utf-8", errors="replace")[:MAX_LOG_LINE_LENGTH])
        if not accepted:
            return
        # Off the event loop: a plugin that writes fast cannot block the agent's other work.
        await asyncio.to_thread(self._write, accepted)

    def _dropped_notice(self) -> bytes:
        notice = f"[es_plugins] dropped {self._dropped} line(s) over the log rate limit"
        self._tail.append(notice)
        return notice.encode()

    def _write(self, lines: list[bytes]) -> None:
        self._log_file.write_lines(lines)
        prefix = f"[{self._identifier}] "
        self._echo.write(
            "".join(prefix + line.decode("utf-8", errors="replace") + "\n" for line in lines)
        )
        self._echo.flush()

    def close(self) -> None:
        self._log_file.close()
