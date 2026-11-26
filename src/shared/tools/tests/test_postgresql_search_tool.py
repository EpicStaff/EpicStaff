"""What postgresql_search_tool lets an agent do to a real PostgreSQL database.

The tool runs in the sandbox, invoked by an agent; the args_schema config
fields (db_uri, read_only) arrive as module-level globals via `global_kwargs`.
Each test builds those globals and then calls `main()` the way the sandbox does.

Read-only mode is enforced by the database, not by parsing: the query runs in
pipeline mode over the extended query protocol (PostgreSQL rejects a second
statement in it) inside a READ ONLY transaction that is rolled back. `_validate_query`'s sqlparse check is
only an early, friendlier error message -- sqlparse does not split statements
the way PostgreSQL does, so the enforcement tests run against a real server.
"""

import json
import sys
from urllib.parse import urlsplit, urlunsplit

import pytest

from conftest import TOOLS_ROOT, load_tool_main

# The .invalid top-level domain never resolves, so connecting fails at once.
UNREACHABLE_URI = "postgresql://user:secret-password@db.invalid:5432/db"

# sqlparse treats the backslash as an escape inside '...', so it reads this as
# one SELECT. PostgreSQL (standard_conforming_strings=on) ends the string at the
# second quote and sees several statements; the trailing `--'` hides the last quote.
# The payload commits its INSERT itself, so the tool's closing rollback could not
# undo it: only the server refusing the second statement keeps the row out.
BACKSLASH_COMMIT_PAYLOAD = (
    "SELECT '\\'; COMMIT; BEGIN READ WRITE; INSERT INTO victim VALUES (666); COMMIT; --'"
)
WRITING_CTE = (
    "WITH written AS (INSERT INTO victim VALUES (666) RETURNING *) SELECT * FROM written"
)
# sqlparse ends a block comment at the first `*/`, so it reads `SELECT */ INSERT ...`
# as a SELECT. PostgreSQL nests block comments and runs one INSERT.
NESTED_COMMENT_INSERT = "/* /* */ SELECT */ INSERT INTO victim VALUES (666)"


def _tool_module(**injected_globals):
    module = load_tool_main("postgresql_search_tool")
    module.__dict__.update(injected_globals)
    return module


def _require_docker():
    docker = pytest.importorskip("docker")
    try:
        docker.from_env().ping()
    except Exception:
        pytest.skip("Docker is not available")


@pytest.fixture(scope="module")
def postgres_uri():
    """A throwaway PostgreSQL server; yields a libpq URI (postgresql://...)."""
    _require_docker()
    postgres = pytest.importorskip("testcontainers.postgres")

    with postgres.PostgresContainer("postgres:17.5", driver=None) as container:
        yield container.get_connection_url()


@pytest.fixture
def victim_rows(postgres_uri):
    """Create an empty `victim (id int)` table; returns a function reading its ids
    over a separate connection, so it sees only what was committed."""
    import psycopg

    with psycopg.connect(postgres_uri, autocommit=True) as connection:
        connection.execute("DROP TABLE IF EXISTS victim")
        connection.execute("CREATE TABLE victim (id int)")

    def read_ids():
        with psycopg.connect(postgres_uri, autocommit=True) as connection:
            rows = connection.execute("SELECT id FROM victim ORDER BY id").fetchall()
        return [row[0] for row in rows]

    return read_ids


def test_read_only_mode_rejects_statements_sqlparse_counts_as_one_select(
    postgres_uri, victim_rows
):
    module = _tool_module(db_uri=postgres_uri, read_only=True)

    result = module.main(BACKSLASH_COMMIT_PAYLOAD)

    assert result == {"error": "SyntaxError"}
    assert victim_rows() == []


def test_read_write_mode_also_runs_only_one_statement_per_call(postgres_uri, victim_rows):
    module = _tool_module(db_uri=postgres_uri, read_only=False)

    result = module.main("SELECT '\\'; INSERT INTO victim VALUES (666); --'")

    assert result == {"error": "SyntaxError"}
    assert victim_rows() == []


@pytest.mark.parametrize(
    "write_sqlparse_reads_as_select",
    [WRITING_CTE, NESTED_COMMENT_INSERT],
    ids=["data-modifying-cte", "nested-block-comment"],
)
def test_read_only_mode_rejects_one_write_that_sqlparse_reads_as_select(
    postgres_uri, victim_rows, write_sqlparse_reads_as_select
):
    module = _tool_module(db_uri=postgres_uri, read_only=True)

    result = module.main(write_sqlparse_reads_as_select)

    assert result == {"error": "ReadOnlySqlTransaction"}
    assert victim_rows() == []


def test_read_only_mode_returns_selected_rows(postgres_uri):
    module = _tool_module(db_uri=postgres_uri, read_only=True)

    result = module.main("SELECT 1 AS id, 'x' AS name UNION ALL SELECT 2, '%y%' ORDER BY id")

    assert result == [{"id": 1, "name": "x"}, {"id": 2, "name": "%y%"}]


def test_read_only_mode_reports_an_empty_result(postgres_uri, victim_rows):
    module = _tool_module(db_uri=postgres_uri, read_only=True)

    result = module.main("SELECT id FROM victim")

    assert result == 'Query "SELECT id FROM victim" executed successfully, but returned no rows.'


def test_read_write_mode_commits_a_write(postgres_uri, victim_rows):
    module = _tool_module(db_uri=postgres_uri, read_only=False)

    result = module.main("INSERT INTO victim VALUES (1), (2)")

    assert result == {
        "info": 'Query "INSERT INTO victim VALUES (1), (2)" executed successfully. '
        "2 row(s) affected."
    }
    assert victim_rows() == [1, 2]


def test_read_write_mode_runs_ddl(postgres_uri, victim_rows):
    module = _tool_module(db_uri=postgres_uri, read_only=False)

    result = module.main("ALTER TABLE victim ADD COLUMN name text")

    assert result == {
        "info": 'Query "ALTER TABLE victim ADD COLUMN name text" executed successfully. '
        "0 row(s) affected."
    }
    assert module.main("SELECT name FROM victim") == (
        'Query "SELECT name FROM victim" executed successfully, but returned no rows.'
    )


@pytest.fixture
def read_only_role_uri(postgres_uri, victim_rows):
    """URI of a role whose own default is default_transaction_read_only = on,
    with write privileges on `victim` so only that default can stop a write."""
    import psycopg

    role = "default_read_only_role"
    with psycopg.connect(postgres_uri, autocommit=True) as connection:
        connection.execute(f"DROP ROLE IF EXISTS {role}")
        connection.execute(f"CREATE ROLE {role} LOGIN PASSWORD 'role-password'")
        connection.execute(f"ALTER ROLE {role} SET default_transaction_read_only = on")
        connection.execute(f"GRANT ALL ON victim TO {role}")

    parts = urlsplit(postgres_uri)
    netloc = f"{role}:role-password@{parts.hostname}:{parts.port}"
    yield urlunsplit(parts._replace(netloc=netloc))

    with psycopg.connect(postgres_uri, autocommit=True) as connection:
        connection.execute(f"DROP OWNED BY {role}")
        connection.execute(f"DROP ROLE {role}")


def test_read_write_mode_keeps_a_role_default_of_read_only(read_only_role_uri, victim_rows):
    module = _tool_module(db_uri=read_only_role_uri, read_only=False)

    result = module.main("INSERT INTO victim VALUES (666)")

    assert result == {"error": "ReadOnlySqlTransaction"}
    assert victim_rows() == []


@pytest.fixture
def reused_backend(postgres_uri, monkeypatch):
    """Make every psycopg.connect return one session that stays open, the way a
    transaction-mode pooler hands the next client the same backend; returns a
    function listing the prepared statements left in that session."""
    import psycopg
    from psycopg.rows import dict_row

    class KeptOpenConnection(psycopg.Connection):
        def close(self):
            pass

    session = KeptOpenConnection.connect(postgres_uri, row_factory=dict_row)
    monkeypatch.setattr(psycopg, "connect", lambda conninfo, **kwargs: session)

    def prepared_statements():
        with session.cursor() as cursor:
            cursor.execute("SELECT name FROM pg_prepared_statements", prepare=False)
            rows = cursor.fetchall()
        session.rollback()
        return [row["name"] for row in rows]

    yield prepared_statements
    psycopg.Connection.close(session)


# A failed query must not leave a statement behind either: the transaction's
# rollback does not remove prepared statements.
@pytest.mark.parametrize(
    "sql_query, read_only, expected_result",
    [
        (
            "SELECT id FROM victim",
            True,
            'Query "SELECT id FROM victim" executed successfully, but returned no rows.',
        ),
        (
            "SELECT id FROM victim",
            False,
            'Query "SELECT id FROM victim" executed successfully, but returned no rows.',
        ),
        ("SELECT 1/0", True, {"error": "DivisionByZero"}),
        ("SELECT 1/0", False, {"error": "DivisionByZero"}),
        (WRITING_CTE, True, {"error": "ReadOnlySqlTransaction"}),
    ],
    ids=[
        "success-read-only",
        "success-read-write",
        "runtime-error-read-only",
        "runtime-error-read-write",
        "write-refused-in-read-only",
    ],
)
def test_no_prepared_statement_is_left_on_the_backend(
    reused_backend, victim_rows, sql_query, read_only, expected_result
):
    module = _tool_module(db_uri="postgresql://pooled", read_only=read_only)

    assert module.main(sql_query) == expected_result
    assert reused_backend() == []


def test_sqlalchemy_style_uri_naming_a_driver_is_accepted(postgres_uri):
    # Configurations saved while the tool ran on SQLAlchemy name a driver in the
    # scheme, as the db_uri description used to show.
    sqlalchemy_uri = postgres_uri.replace("postgresql://", "postgresql+psycopg2://", 1)
    module = _tool_module(db_uri=sqlalchemy_uri, read_only=True)

    assert module.main("SELECT 1 AS one") == [{"one": 1}]


@pytest.mark.parametrize(
    "sql_query, read_only, expected_error",
    [
        ("DROP TABLE users", True, "Only SELECT queries are allowed in read-only mode (got DROP)."),
        ("DROP TABLE users", None, "Only SELECT queries are allowed in read-only mode (got DROP)."),
        ("SELECT 1; SELECT 2", True, "Multiple statements are not allowed."),
        ("SELECT 1; SELECT 2", False, "Multiple statements are not allowed."),
        ("   ", True, "Empty SQL query."),
    ],
)
def test_pre_check_answers_obvious_misuse_before_connecting(sql_query, read_only, expected_error):
    module = _tool_module(db_uri=UNREACHABLE_URI, read_only=read_only)

    assert module.main(sql_query) == {"error": expected_error}


def test_read_only_defaults_to_true_when_not_configured():
    module = _tool_module(db_uri=UNREACHABLE_URI)

    assert module.main("DROP TABLE users") == {
        "error": "Only SELECT queries are allowed in read-only mode (got DROP)."
    }


def test_venv_without_psycopg_gets_an_error_message_not_a_crash(monkeypatch):
    # A venv built for the SQLAlchemy version of the tool has psycopg2, not psycopg.
    monkeypatch.setitem(sys.modules, "psycopg", None)
    module = _tool_module(db_uri=UNREACHABLE_URI, read_only=True)

    result = module.main("SELECT 1")

    assert result == {
        "error": "psycopg is not installed in this tool's venv: add psycopg[binary] to it."
    }


def test_missing_db_uri_is_reported_as_error_in_main():
    module = _tool_module(read_only=True)

    result = module.main("SELECT 1")

    assert "db_uri" in result["error"]


def test_connection_failure_is_reported_without_leaking_the_uri():
    module = _tool_module(db_uri=UNREACHABLE_URI, read_only=False)

    result = module.main("SELECT 1")

    assert result == {"error": "OperationalError"}
    assert "secret-password" not in str(result)


def test_stray_config_kwarg_is_absorbed_and_globals_win():
    """Regression test: python_code.global_kwargs folds user_input config
    into func_kwargs, so main() may also receive config fields as kwargs.
    The globals remain the source of truth; a stray kwarg must be swallowed
    by **kwargs without a TypeError."""
    module = _tool_module(db_uri=UNREACHABLE_URI, read_only=True)

    result = module.main("DROP TABLE users", db_uri="unused-stray-kwarg", read_only=False)

    assert result == {"error": "Only SELECT queries are allowed in read-only mode (got DROP)."}


def test_the_agent_can_neither_see_nor_set_the_connection_settings():
    schema = json.loads((TOOLS_ROOT / "postgresql_search_tool" / "args_schema.json").read_text())

    for field in ("db_uri", "read_only"):
        assert schema["properties"][field]["input_type"] == "user_input"

    assert "db_uri" in schema["required"]
    assert "read_only" not in schema["required"]
