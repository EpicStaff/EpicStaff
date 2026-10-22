"""Running the PostgreSQL client tools: stand-in tools that record what they were given."""

import asyncio
import os
from pathlib import Path

import pytest
from src.shared.models.plugin_nodes import DesiredDatabaseServer

from es_plugins.database.connections import BACKUP_SESSION_OPTIONS
from es_plugins.database.postgres_client import (
    KEEPALIVE_CONNINFO,
    PostgresClient,
    PostgresToolError,
    ToolLogin,
)

PASSWORD = "backup-password-" + "x" * 40
LOGIN = ToolLogin(
    server=DesiredDatabaseServer(name="plugins_db", host="plugins_db", port=5432),
    database="plugin_weather",
    user="plugins_backup",
    password=PASSWORD,
    options=BACKUP_SESSION_OPTIONS,
    application_name="epicstaff-node-backup",
)
# What sh itself puts in a child's environment.
SHELL_VARIABLES = {"PWD", "SHLVL", "_", "OLDPWD"}


def tool(root: Path, name: str, script: str) -> Path:
    path = root / "bin" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + script)
    path.chmod(0o755)
    return path


def recording_tool(root: Path, name: str, output: str = "") -> Path:
    """A tool that writes its environment and arguments next to itself, then `output`."""
    record = root / f"{name}.record"
    return tool(
        root,
        name,
        f"env > '{record}.env'\nfor argument in \"$@\"; do echo \"$argument\"; done > '{record}.argv'\n"
        f"printf '%s' '{output}'\n",
    )


def recorded(root: Path, name: str) -> tuple[dict[str, str], list[str]]:
    environment = dict(
        line.split("=", 1) for line in (root / f"{name}.record.env").read_text().splitlines() if "=" in line
    )
    return environment, (root / f"{name}.record.argv").read_text().splitlines()


async def collect(client: PostgresClient, *arguments, **options) -> bytes:
    output = bytearray()

    async def keep(chunk: bytes) -> bool:
        output.extend(chunk)
        return True

    await client.run(*arguments, stdout=keep, **options)
    return bytes(output)


async def test_a_run_that_connects_gets_its_login_in_the_environment_and_nothing_secret_in_argv(tmp_path):
    recording_tool(tmp_path, "pg_dump", "PGDMP")

    output = await collect(PostgresClient(tmp_path), "pg_dump", ["--format=custom"], login=LOGIN)

    environment, argv = recorded(tmp_path, "pg_dump")
    assert output == b"PGDMP"
    assert {name: value for name, value in environment.items() if name not in SHELL_VARIABLES} == {
        "LANG": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "LD_LIBRARY_PATH": str(tmp_path / "lib"),
        "PGPASSFILE": "/dev/null",
        "PGSERVICEFILE": "/dev/null",
        "PGHOST": "plugins_db",
        "PGPORT": "5432",
        "PGDATABASE": "plugin_weather",
        "PGUSER": "plugins_backup",
        "PGPASSWORD": PASSWORD,
        "PGREQUIREAUTH": "scram-sha-256",
        "PGCONNECT_TIMEOUT": "10",
        "PGAPPNAME": "epicstaff-node-backup",
        "PGOPTIONS": BACKUP_SESSION_OPTIONS,
    }
    assert argv == [f"--dbname={KEEPALIVE_CONNINFO}", "--format=custom"]
    assert not any(PASSWORD in argument for argument in argv)


async def test_a_run_that_only_reads_an_archive_gets_no_login_and_no_password(tmp_path):
    recording_tool(tmp_path, "pg_restore")

    await PostgresClient(tmp_path).run("pg_restore", ["--list"])

    environment, argv = recorded(tmp_path, "pg_restore")
    assert not [name for name in environment if name.startswith("PG") and name not in ("PGPASSFILE", "PGSERVICEFILE")]
    assert PASSWORD not in "".join(environment.values())
    assert argv == ["--list"]


async def test_the_archive_reaches_the_tool_on_its_standard_input(tmp_path):
    tool(tmp_path, "pg_restore", "cat\n")
    archive = tmp_path / "backup.dump"
    archive.write_bytes(b"PGDMP\x00" + os.urandom(3 * 1024 * 1024))

    output = await collect(PostgresClient(tmp_path), "pg_restore", ["--list"], stdin=archive)

    assert output == archive.read_bytes()


async def test_a_sink_that_wants_no_more_ends_the_tool_without_an_error(tmp_path):
    tool(tmp_path, "pg_restore", f"echo $$ > '{tmp_path}/pid'\nwhile :; do echo line; done\n")
    seen = []

    async def first_lines(chunk: bytes) -> bool:
        seen.append(chunk)
        return False

    await PostgresClient(tmp_path).run("pg_restore", ["--data-only"], stdout=first_lines)

    assert seen and seen[0].startswith(b"line")
    pid = int((tmp_path / "pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


async def test_a_failure_keeps_the_tools_own_lines_and_never_a_rows_contents(tmp_path):
    tool(
        tmp_path,
        "pg_restore",
        "echo 'pg_restore: error: could not execute query: ERROR:  duplicate key value' >&2\n"
        "echo 'DETAIL:  Key (name)=(secret row value) already exists.' >&2\n"
        "echo 'CONTEXT:  COPY places, line 3: \"secret row value\"' >&2\n"
        "echo 'Command was: COPY app.places FROM stdin;' >&2\n"
        "printf 'pg_restore: error: an object\\tnamed \\033[31mred\\033[0m\\n' >&2\n"
        "echo 'pg_dump: detail: Query was: COPY app.places TO stdout;' >&2\n"
        "exit 3\n",
    )

    with pytest.raises(PostgresToolError) as failed:
        await PostgresClient(tmp_path).run("pg_restore", ["--single-transaction"])

    message = str(failed.value)
    assert message.startswith("pg_restore exited with status 3: ")
    assert "duplicate key value" in message
    assert "secret row value" not in message and "Command was" not in message and "Query was" not in message
    assert "\x1b" not in message and "\t" not in message
    assert failed.value.error_lines[-1] == "pg_restore: error: an object named [31mred [0m"


async def test_every_line_of_a_failed_statement_is_left_out_until_the_tools_next_line(tmp_path):
    tool(
        tmp_path,
        "pg_restore",
        "echo 'pg_restore: error: could not execute query: ERROR:  syntax error' >&2\n"
        "echo 'Command was: CREATE FUNCTION app.f() RETURNS text' >&2\n"
        "echo \"    AS \\$\\$ SELECT 'secret row value' \\$\\$\" >&2\n"
        "echo '    LANGUAGE sql;' >&2\n"
        "echo 'pg_restore: warning: errors ignored on restore: 1' >&2\n"
        "exit 1\n",
    )

    with pytest.raises(PostgresToolError) as failed:
        await PostgresClient(tmp_path).run("pg_restore", [])

    assert failed.value.error_lines == (
        "pg_restore: error: could not execute query: ERROR: syntax error",
        "pg_restore: warning: errors ignored on restore: 1",
    )
    assert "secret row value" not in str(failed.value) and "LANGUAGE" not in str(failed.value)


async def test_a_failure_keeps_the_tools_first_line_whatever_follows(tmp_path):
    tool(
        tmp_path,
        "pg_dump",
        "echo 'pg_dump: error: connection to server at \"plugins_db\" (10.0.0.1), port 5432 failed: Connection refused' >&2\n"
        "for line in 1 2 3 4 5; do echo \"pg_dump: detail: $line\" >&2; done\n"
        "exit 1\n",
    )

    with pytest.raises(PostgresToolError) as failed:
        await PostgresClient(tmp_path).run("pg_dump", [], login=LOGIN)

    assert failed.value.first_line.startswith("pg_dump: error: connection to server at")


async def test_a_failure_without_any_error_output_has_no_first_line(tmp_path):
    tool(tmp_path, "pg_dump", "exit 1\n")

    with pytest.raises(PostgresToolError) as failed:
        await PostgresClient(tmp_path).run("pg_dump", [], login=LOGIN)

    assert failed.value.first_line is None


async def test_a_cancelled_run_kills_the_tool(tmp_path):
    tool(tmp_path, "pg_dump", f"echo $$ > '{tmp_path}/pid'\nexec sleep 60\n")
    run = asyncio.create_task(PostgresClient(tmp_path).run("pg_dump", [], login=LOGIN))
    while not (tmp_path / "pid").exists():
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.1)

    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run

    pid = int((tmp_path / "pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


async def test_the_version_is_the_tools_first_line(tmp_path):
    tool(tmp_path, "pg_dump", "echo 'pg_dump (PostgreSQL) 17.11 (Debian 17.11-1.pgdg12+2)'\necho second\n")

    assert await PostgresClient(tmp_path).version("pg_dump") == "pg_dump (PostgreSQL) 17.11 (Debian 17.11-1.pgdg12+2)"
