"""What a backup's archive holds, read with `pg_restore` alone: no session, no password.

- `check_archive`: `pg_restore --list` reads the whole table of contents (an archive it cannot
  read is not a backup), and whether it lists the data of the migration ledger
  (`TABLE DATA _epicstaff migrations`).
- `read_archive_ledger`: the ledger's rows, from the archive's own copy of the table. The
  platform never reads the ledger as the backup role from the live database: the owner can
  replace that table with a view, and the view's functions would then run as the backup role.

The ledger is the plugin's, so it is read bounded: at most `MAX_APPLIED_MIGRATIONS + 1` rows and
lines of at most `MAX_LINE_BYTES`, and only entries `is_reportable_ledger_entry` accepts are kept.
"""

from pathlib import Path

from epicstaff_plugin.contracts.database import MIGRATIONS_LEDGER_SCHEMA, MIGRATIONS_LEDGER_TABLE
from src.shared.models.plugin_nodes import (
    MAX_APPLIED_MIGRATIONS,
    LedgerEntry,
    is_reportable_ledger_entry,
)

from es_plugins.database.postgres_client import PostgresClient

MAX_LINE_BYTES = 64 * 1024
_LEDGER_DATA_ENTRY = ("TABLE", "DATA", MIGRATIONS_LEDGER_SCHEMA, MIGRATIONS_LEDGER_TABLE)
_COPY_HEADER = f"COPY {MIGRATIONS_LEDGER_SCHEMA}.{MIGRATIONS_LEDGER_TABLE} ("
_COPY_END = "\\."
_COPY_ESCAPES = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v"}


class _Lines:
    """Splits a tool's output into lines as it arrives; `line` is called for each."""

    def __init__(self, line):
        self._line = line
        self._pending = b""
        self.overlong = False

    async def __call__(self, chunk: bytes) -> bool:
        self._pending += chunk
        *lines, self._pending = self._pending.split(b"\n")
        if len(self._pending) > MAX_LINE_BYTES or any(len(line) > MAX_LINE_BYTES for line in lines):
            self.overlong = True
            return False
        return all(self._line(line.decode(errors="replace")) for line in lines)


async def check_archive(client: PostgresClient, archive: Path) -> bool:
    """Whether `pg_restore --list` reads the archive and lists the ledger's table data.

    Raises:
        PostgresToolError: `pg_restore` could not read the archive.
    """
    found = False

    def look(line: str) -> bool:
        nonlocal found
        # "<id>; <oid> <oid> TABLE DATA _epicstaff migrations <owner>"
        words = line.split(" ")
        if len(words) == 8 and tuple(words[3:7]) == _LEDGER_DATA_ENTRY:
            found = True
        return True

    lines = _Lines(look)
    await client.run("pg_restore", ["--list"], stdin=archive, stdout=lines)
    return found and not lines.overlong


async def read_archive_ledger(
    client: PostgresClient, archive: Path
) -> tuple[LedgerEntry, ...] | None:
    """The ledger the archive holds, oldest first; None when its rows cannot be read.

    Raises:
        PostgresToolError: `pg_restore` could not read the archive.
    """
    columns: list[str] | None = None
    rows: list[list[str | None]] = []
    finished = False

    def take(line: str) -> bool:
        nonlocal columns, finished
        if columns is None:
            if line.startswith(_COPY_HEADER) and line.endswith(") FROM stdin;"):
                columns = [
                    name.strip().strip('"')
                    for name in line[len(_COPY_HEADER) : -len(") FROM stdin;")].split(",")
                ]
            return True
        if line == _COPY_END:
            finished = True
            return False
        rows.append([_copy_field(field) for field in line.split("\t")])
        return len(rows) <= MAX_APPLIED_MIGRATIONS

    lines = _Lines(take)
    await client.run(
        "pg_restore",
        [
            "--data-only",
            f"--schema={MIGRATIONS_LEDGER_SCHEMA}",
            f"--table={MIGRATIONS_LEDGER_TABLE}",
            "--file=-",
        ],
        stdin=archive,
        stdout=lines,
    )
    if lines.overlong or columns is None or "name" not in columns or "sha256" not in columns:
        return None
    if not finished and len(rows) <= MAX_APPLIED_MIGRATIONS:
        return None
    name_at, sha256_at = columns.index("name"), columns.index("sha256")
    return tuple(
        LedgerEntry(name=row[name_at], sha256=row[sha256_at])
        for row in rows[:MAX_APPLIED_MIGRATIONS]
        if len(row) == len(columns) and is_reportable_ledger_entry(row[name_at], row[sha256_at])
    )


def _copy_field(text: str) -> str | None:
    """One field of `COPY … TO` text output: `\\N` is NULL, backslash escapes are undone."""
    if text == "\\N":
        return None
    if "\\" not in text:
        return text
    characters = []
    position = 0
    while position < len(text):
        character = text[position]
        position += 1
        if character != "\\" or position == len(text):
            characters.append(character)
            continue
        escaped = text[position]
        position += 1
        characters.append(_COPY_ESCAPES.get(escaped, escaped))
    return "".join(characters)
