"""How mysql_search_tool picks up its db_uri / read_only config fields.

The tool runs in the sandbox, invoked by an agent; the args_schema config
fields arrive as module-level globals via `global_kwargs`. Each test builds
the globals and then asserts behaviour the user can see — which URI is
connected to, and whether a write statement is accepted.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from conftest import TOOLS_ROOT, load_tool_main

# mysql_search_tool/main.py imports sqlalchemy and sqlparse at module level.
# Per its requirements.txt those are installed into the tool's own venv by the
# sandbox at execution time, not into any service venv — skip cleanly instead
# of failing when running outside that venv.
pytest.importorskip(
    "sqlalchemy",
    reason="installed by the sandbox into this tool's own venv, not a service venv",
)
pytest.importorskip(
    "sqlparse",
    reason="installed by the sandbox into this tool's own venv, not a service venv",
)

CONFIG_URI = "mysql+pymysql://user:pass@config-host/db"


def _tool_module(**injected_globals):
    module = load_tool_main("mysql_search_tool")
    module.__dict__.update(injected_globals)
    return module


def _run(module, sql_query, returns_rows=True, rows=(), **main_kwargs):
    """Call the tool's entrypoint against a stand-in engine; returns the
    tool's result and the URI it connected to.

    `event.listens_for` is patched to a no-op here: the connect-listener
    itself (the real read-only boundary, see `_connect_statements` below) is
    tested separately -- these tests only need construction not to crash
    against a bare `MagicMock` engine.
    """
    engine = MagicMock()
    result = engine.connect.return_value.__enter__.return_value.execute.return_value
    result.returns_rows = returns_rows
    result.mappings.return_value = list(rows)
    result.rowcount = len(rows)

    with (
        patch.object(module, "create_engine", return_value=engine) as create_engine,
        patch.object(module.event, "listens_for"),
    ):
        tool_result = module.main(sql_query, **main_kwargs)

    connected_uri = create_engine.call_args.args[0] if create_engine.call_args else None
    return tool_result, connected_uri


def _connect_statements(module):
    """Construct the tool against a stand-in engine; returns the statements
    a new connection runs before any query -- this is what actually enforces
    read-only (the database rejects them), unlike `_validate_query`'s
    sqlparse-based pre-check, which a data-modifying CTE can slip past."""
    engine = MagicMock()
    connect_listeners = []

    def listens_for(target, identifier):
        assert (target, identifier) == (engine, "connect")
        return lambda listener: connect_listeners.append(listener) or listener

    with (
        patch.object(module, "create_engine", return_value=engine),
        patch.object(module.event, "listens_for", side_effect=listens_for),
    ):
        module.MySQLSearchTool()

    connection = MagicMock()
    for listener in connect_listeners:
        listener(connection, None)
    return [
        call.args[0] for call in connection.cursor.return_value.execute.call_args_list
    ]


def test_config_field_uses_db_uri_and_read_only():
    module = _tool_module(db_uri=CONFIG_URI, read_only=False)

    result, connected_uri = _run(module, "DELETE FROM users WHERE id = 1", returns_rows=False)

    assert connected_uri == CONFIG_URI
    assert "executed successfully" in result["info"]


def test_read_only_defaults_to_true_when_not_configured():
    module = _tool_module(db_uri=CONFIG_URI)

    result, _ = _run(module, "DROP TABLE users", returns_rows=False)

    assert result == {"error": "Only SELECT queries are allowed in read-only mode (got DROP)."}


def test_read_only_false_allows_write_queries():
    module = _tool_module(db_uri=CONFIG_URI, read_only=False)

    result, _ = _run(module, "INSERT INTO users (name) VALUES ('x')", returns_rows=False)

    assert "error" not in result


def test_read_only_none_from_config_defaults_to_true():
    module = _tool_module(db_uri=CONFIG_URI, read_only=None)

    result, _ = _run(module, "DROP TABLE users", returns_rows=False)

    assert result == {"error": "Only SELECT queries are allowed in read-only mode (got DROP)."}


def test_missing_db_uri_is_reported_as_error_in_main():
    module = _tool_module(read_only=True)

    result, connected_uri = _run(module, "SELECT 1")

    assert connected_uri is None
    assert "db_uri" in result["error"]


def test_the_agent_can_neither_see_nor_set_the_connection_settings():
    schema = json.loads((TOOLS_ROOT / "mysql_search_tool" / "args_schema.json").read_text())

    for field in ("db_uri", "read_only"):
        assert schema["properties"][field]["input_type"] == "user_input"

    assert "db_uri" in schema["required"]
    assert "read_only" not in schema["required"]


def test_read_only_mode_still_runs_select_queries():
    module = _tool_module(db_uri=CONFIG_URI)

    result, _ = _run(module, "SELECT id FROM users", rows=[{"id": 1}])

    assert result == [{"id": 1}]


def test_read_only_is_enforced_at_the_connection_not_just_by_query_parsing():
    # Regression test: a data-modifying CTE slips past _validate_query's
    # sqlparse check but not this connect-time statement (see main.py).
    module = _tool_module(db_uri=CONFIG_URI, read_only=True)

    statements = _connect_statements(module)

    assert statements == [module.READ_ONLY_STATEMENT]


def test_read_write_mode_does_not_register_a_connect_listener():
    module = _tool_module(db_uri=CONFIG_URI, read_only=False)

    statements = _connect_statements(module)

    assert statements == []


def test_db_execution_failure_is_reported_without_leaking_its_content():
    module = _tool_module(db_uri=CONFIG_URI, read_only=False)
    engine = MagicMock()
    engine.connect.side_effect = ConnectionError(f"could not connect to {CONFIG_URI}")

    with (
        patch.object(module, "create_engine", return_value=engine),
        patch.object(module.event, "listens_for"),
    ):
        result = module.main("SELECT 1")

    assert result == {"error": "ConnectionError"}
    assert CONFIG_URI not in str(result)


def test_stray_config_kwarg_is_absorbed_and_globals_win():
    """Regression test: python_code.global_kwargs folds user_input config
    into func_kwargs, so main() may also receive config fields as kwargs.
    The globals remain the source of truth; a stray kwarg must be swallowed
    by **kwargs without a TypeError."""
    module = _tool_module(db_uri=CONFIG_URI, read_only=False)

    result, connected_uri = _run(
        module, "SELECT 1", rows=[{"id": 1}], db_uri="unused-stray-kwarg"
    )

    assert connected_uri == CONFIG_URI
    assert result == [{"id": 1}]
