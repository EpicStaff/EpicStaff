"""What an archive holds, read with a stand-in `pg_restore` that prints what the real one would."""

import pytest
from src.shared.models.plugin_nodes import MAX_APPLIED_MIGRATIONS, LedgerEntry

from es_plugins.database.archive import MAX_LINE_BYTES, check_archive, read_archive_ledger
from es_plugins.database.postgres_client import PostgresClient, PostgresToolError

LISTING = """;
; Archive created at 2026-10-21 21:14:20 UTC
;     dbname: plugin_weather
;
3441; 2615 17770 SCHEMA - _epicstaff weather_owner
3442; 1259 17771 TABLE _epicstaff migrations weather_owner
3519; 0 17771 TABLE DATA _epicstaff migrations weather_owner
3520; 0 16613 TABLE DATA weather saved_places weather_owner
"""
LEDGER_SCRIPT = """\\restrict nXrmQCih6N1iNdI46Os
SET statement_timeout = 0;
SELECT pg_catalog.set_config('search_path', '', false);

--
-- Data for Name: migrations; Type: TABLE DATA; Schema: _epicstaff; Owner: weather_owner
--

COPY _epicstaff.migrations (name, sha256, applied_at) FROM stdin;
{rows}\\.

\\unrestrict nXrmQCih6N1iNdI46Os
"""


def pg_restore(root, output: str, status: int = 0):
    """A `pg_restore` printing `output`, whatever it was asked; the archive is its stdin."""
    script = root / "bin" / "pg_restore"
    script.parent.mkdir(parents=True, exist_ok=True)
    (root / "output").write_text(output)
    script.write_text(f"#!/bin/sh\ncat > /dev/null\ncat '{root}/output'\nexit {status}\n")
    script.chmod(0o755)
    archive = root / "backup.dump"
    archive.write_bytes(b"PGDMP")
    return PostgresClient(root), archive


async def test_an_archive_listing_the_ledgers_data_passes(tmp_path):
    client, archive = pg_restore(tmp_path, LISTING)

    assert await check_archive(client, archive)


async def test_an_archive_without_the_ledgers_data_fails(tmp_path):
    client, archive = pg_restore(
        tmp_path, LISTING.replace("TABLE DATA _epicstaff migrations", "TABLE _epicstaff migrations")
    )

    assert not await check_archive(client, archive)


async def test_a_lookalike_table_is_not_the_ledger(tmp_path):
    client, archive = pg_restore(
        tmp_path,
        "3519; 0 17771 TABLE DATA _epicstaff migrations x weather_owner\n",
    )

    assert not await check_archive(client, archive)


async def test_an_archive_pg_restore_cannot_read_fails_with_its_error(tmp_path):
    client, archive = pg_restore(tmp_path, "", status=1)

    with pytest.raises(PostgresToolError):
        await check_archive(client, archive)


async def test_the_ledger_is_read_from_the_archives_copy_of_the_table(tmp_path):
    rows = "001_weather.sql\t" + "a" * 64 + "\t2026-10-21 10:00:00+00\n002_tab\\there.sql\t" + "b" * 64 + "\t\\N\n"
    client, archive = pg_restore(tmp_path, LEDGER_SCRIPT.format(rows=rows))

    ledger = await read_archive_ledger(client, archive)

    # A name with a tab in it is no migration file name: the ledger keeps only reportable rows.
    assert ledger == (LedgerEntry(name="001_weather.sql", sha256="a" * 64),)


async def test_the_columns_are_found_by_name(tmp_path):
    script = LEDGER_SCRIPT.replace("(name, sha256, applied_at)", "(applied_at, sha256, note, name)")
    rows = "2026-10-21 10:00:00+00\t" + "c" * 64 + "\t\\N\t003_last.sql\n"
    client, archive = pg_restore(tmp_path, script.format(rows=rows))

    assert await read_archive_ledger(client, archive) == (LedgerEntry(name="003_last.sql", sha256="c" * 64),)


async def test_a_ledger_without_a_name_or_digest_column_is_unknown(tmp_path):
    script = LEDGER_SCRIPT.replace("(name, sha256, applied_at)", "(name, applied_at)")
    client, archive = pg_restore(tmp_path, script.format(rows="001_weather.sql\t\\N\n"))

    assert await read_archive_ledger(client, archive) is None


async def test_a_ledger_the_archive_does_not_hold_is_unknown(tmp_path):
    client, archive = pg_restore(tmp_path, "SET statement_timeout = 0;\n")

    assert await read_archive_ledger(client, archive) is None


async def test_a_huge_ledger_is_read_bounded(tmp_path):
    rows = "".join(f"{number:03d}_m.sql\t{'d' * 64}\t\\N\n" for number in range(1000)) * 3
    client, archive = pg_restore(tmp_path, LEDGER_SCRIPT.format(rows=rows))

    ledger = await read_archive_ledger(client, archive)

    assert ledger is not None and len(ledger) == MAX_APPLIED_MIGRATIONS


async def test_an_overlong_line_makes_the_ledger_unknown(tmp_path):
    rows = "001_weather.sql\t" + "x" * (MAX_LINE_BYTES + 10) + "\n"
    client, archive = pg_restore(tmp_path, LEDGER_SCRIPT.format(rows=rows))

    assert await read_archive_ledger(client, archive) is None
