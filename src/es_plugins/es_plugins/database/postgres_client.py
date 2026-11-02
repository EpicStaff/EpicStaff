"""Run `pg_dump` and `pg_restore`, the PostgreSQL client tools of plugins_db's major version.

The image carries them, with their `libpq`, under `POSTGRES_CLIENT_ROOT` (see the Dockerfile).
Every run gets an environment built here and nothing of the agent's, whose own environment holds
`plugins_admin`'s and `plugins_backup`'s passwords:

- a run that connects gets exactly one login (`ToolLogin`): host, port, database, user and
  password, `require_auth=scram-sha-256`, a connect timeout, an application name and the session
  options that override the plugin's stored settings (`connections`);
- a run that only reads an archive gets no login and no password at all.

Nothing secret is in a command line, which every process on the node can read: the only
connection parameters there are the TCP keepalives, which libpq takes from no environment
variable. Archives travel through pipes: `pg_dump` writes to its standard output and the caller
writes the file, `pg_restore` reads the archive from its standard input. So the tools never open
a path of the node's.

A run that fails raises `PostgresToolError` with the tool's last error lines and its first
line. Lines that can carry a row's contents are left out: `DETAIL:`, `CONTEXT:`, and everything
from the first `Command was:` on, the failed statement and every later error, but for
`pg_restore`'s final count of the errors it ignored. Control characters become spaces, since
object names and messages in them are the plugin's.
"""

import asyncio
import contextlib
import re
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from src.shared.models.plugin_nodes import DesiredDatabaseServer

from es_plugins.database.connections import (
    CONNECT_TIMEOUT_SECONDS,
    REQUIRED_AUTHENTICATION,
    describe_text,
)

POSTGRES_CLIENT_ROOT = Path("/opt/postgresql-client/17")
PostgresTool = Literal["pg_dump", "pg_restore"]
# libpq takes these from the connection string only; none of them is secret.
KEEPALIVE_CONNINFO = (
    "keepalives=1 keepalives_idle=30 keepalives_interval=10 keepalives_count=3 "
    "tcp_user_timeout=60000"
)
ERROR_LINES_KEPT = 3
_CHUNK_BYTES = 1024 * 1024
_STREAM_LIMIT_BYTES = 1024 * 1024
_SYSTEM_PATH = "/usr/bin:/bin"
# A tool's own lines start with its name; the server's ERROR text is on the same line.
_ROW_BEARING_PREFIXES = ("DETAIL:", "CONTEXT:", "LINE ")
_STATEMENT_PREFIX = "Command was:"

StdoutSink = Callable[[bytes], Awaitable[bool]]
"""Takes one chunk of a tool's output; returns False once it wants no more (the tool is ended)."""


class PostgresToolError(Exception):
    """`pg_dump` or `pg_restore` failed; the message ends with its last error lines.

    `first_line` is the first line the tool wrote to its standard error, None when it wrote
    none: what libpq says when it could not connect, which nothing of the plugin's can precede.
    """

    def __init__(
        self, message: str, *, error_lines: tuple[str, ...] = (), first_line: str | None = None
    ):
        super().__init__(message)
        self.error_lines = error_lines
        self.first_line = first_line


@dataclass(frozen=True)
class ToolLogin:
    """Who a tool connects as, and to which database."""

    server: DesiredDatabaseServer
    database: str
    user: str
    password: str = field(repr=False)
    options: str
    """`PGOPTIONS`: the session settings, which take precedence over the database's own."""

    application_name: str


class PostgresClient:
    def __init__(
        self,
        root: Path = POSTGRES_CLIENT_ROOT,
        *,
        create_process: Callable[..., Awaitable[asyncio.subprocess.Process]] = (
            asyncio.create_subprocess_exec
        ),
    ):
        """`create_process` is asyncio's `create_subprocess_exec`; tests wrap it."""
        self._root = root
        self._create_process = create_process

    def environment(self, login: ToolLogin | None) -> dict[str, str]:
        """The whole environment of one run."""
        environment = {
            "LANG": "C.UTF-8",
            "PATH": _SYSTEM_PATH,
            "LD_LIBRARY_PATH": str(self._root / "lib"),
            # No password file and no service file: a run uses its login and nothing else.
            "PGPASSFILE": "/dev/null",
            "PGSERVICEFILE": "/dev/null",
        }
        if login is not None:
            environment.update(
                PGHOST=login.server.host,
                PGPORT=str(login.server.port),
                PGDATABASE=login.database,
                PGUSER=login.user,
                PGPASSWORD=login.password,
                PGREQUIREAUTH=REQUIRED_AUTHENTICATION,
                PGCONNECT_TIMEOUT=str(CONNECT_TIMEOUT_SECONDS),
                PGAPPNAME=login.application_name,
                PGOPTIONS=login.options,
            )
        return environment

    async def run(
        self,
        tool: PostgresTool,
        arguments: list[str],
        *,
        login: ToolLogin | None = None,
        stdin: Path | None = None,
        stdout: StdoutSink | None = None,
    ) -> None:
        """Run `tool`, feeding it `stdin` (a file) and handing its output to `stdout`.

        The process is killed when the call is cancelled, and when `stdout` wants no more
        output, which ends the run without an error.

        Raises:
            PostgresToolError: The tool exited with a status other than 0.
        """
        argv = [str(self._root / "bin" / tool), *arguments]
        if login is not None:
            argv.insert(1, f"--dbname={KEEPALIVE_CONNINFO}")
        with contextlib.ExitStack() as files:
            input_descriptor = asyncio.subprocess.DEVNULL
            if stdin is not None:
                archive = await asyncio.to_thread(open, stdin, "rb")
                input_descriptor = files.enter_context(archive).fileno()
            process = await self._create_process(
                *argv,
                stdin=input_descriptor,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.environment(login),
                limit=_STREAM_LIMIT_BYTES,
            )
            errors = _ErrorLines(tool)
            collecting = asyncio.ensure_future(_collect_errors(process.stderr, errors))
            try:
                stopped = await _forward(process.stdout, stdout)
                if stopped:
                    # It may be blocked writing output nobody reads any more.
                    _kill(process)
                    await _discard(process.stdout)
                status = await process.wait()
                await collecting
            except BaseException:
                _kill(process)
                collecting.cancel()
                with contextlib.suppress(ProcessLookupError):
                    await _discard(process.stdout)
                    await process.wait()
                raise
        if status != 0 and not stopped:
            lines = tuple(errors.kept)
            detail = "; ".join(lines) or "no error message"
            raise PostgresToolError(
                f"{tool} exited with status {status}: {detail}",
                error_lines=lines,
                first_line=errors.first,
            )

    async def version(self, tool: PostgresTool) -> str:
        """`<tool> --version`'s first line, e.g. `pg_dump (PostgreSQL) 17.11 (Debian …)`."""
        output = bytearray()

        async def keep(chunk: bytes) -> bool:
            output.extend(chunk[: 4096 - len(output)])
            return len(output) < 4096

        await self.run(tool, ["--version"], stdout=keep)
        return output.decode(errors="replace").strip().splitlines()[0] if output else ""


async def _forward(stream: asyncio.StreamReader, sink: StdoutSink | None) -> bool:
    """Hand the output to `sink` until it ends; return True when `sink` asked to stop early."""
    while chunk := await stream.read(_CHUNK_BYTES):
        if sink is not None and not await sink(chunk):
            return True
    return False


class _ErrorLines:
    """A tool's standard error as it arrives: its first line, and the last lines worth keeping."""

    def __init__(self, tool: PostgresTool):
        self._summary = re.compile(rf"{re.escape(tool)}: warning: errors ignored on restore: \d+")
        self.first: str | None = None
        self.kept: deque[str] = deque(maxlen=ERROR_LINES_KEPT)
        self._after_statement = False

    def add(self, line: str) -> None:
        if not line:
            return
        if self.first is None:
            self.first = line
        if self._after_statement:
            # Past the first failed statement, any line may quote the plugin's SQL or rows.
            if self._summary.fullmatch(line):
                self.kept.append(line)
            return
        if line.startswith(_STATEMENT_PREFIX):
            self._after_statement = True
            return
        if not line.startswith(_ROW_BEARING_PREFIXES) and ": detail:" not in line:
            self.kept.append(line)


async def _discard(stream: asyncio.StreamReader) -> None:
    """Read a killed tool's output to its end.

    asyncio's `wait()` returns only once every pipe has closed, and a pipe whose reader paused
    on a full buffer never sees its end: without this, a tool killed with output still unread
    is waited for forever.
    """
    while await stream.read(_CHUNK_BYTES):
        pass


async def _collect_errors(stream: asyncio.StreamReader, errors: _ErrorLines) -> None:
    while True:
        try:
            raw = await stream.readline()
        except ValueError:
            # A line longer than the stream's limit: keep reading past it.
            await stream.read(_STREAM_LIMIT_BYTES)
            continue
        if not raw:
            return
        errors.add(describe_text(raw.decode(errors="replace")))


def _kill(process: asyncio.subprocess.Process) -> None:
    with contextlib.suppress(ProcessLookupError):
        process.kill()
