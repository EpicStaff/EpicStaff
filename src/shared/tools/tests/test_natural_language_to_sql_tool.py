import json
from unittest.mock import MagicMock, patch

import pytest

from conftest import TOOLS_ROOT, load_tool_main

# natural_language_to_sql_tool/main.py imports sqlalchemy at module level. Per
# tool_data.yaml's requirements.txt, sqlalchemy (and langchain/litellm) are
# installed into this tool's own dedicated venv by the sandbox at execution
# time, not into any service venv — skip cleanly instead of failing when
# running these tests outside that venv.
pytest.importorskip(
    "sqlalchemy",
    reason="installed by the sandbox into this tool's own venv, not a service venv",
)

CONFIGURED_URI = "postgresql+psycopg2://config:pass@localhost/configured"


def _load(**config):
    """Load the tool with config fields as module-level globals.

    `config` becomes the agent flow's injected config-field globals.
    """
    module = load_tool_main("natural_language_to_sql_tool")
    for name, value in config.items():
        setattr(module, name, value)
    return module


def _build_agent(module, tool):
    """Build the SQL agent against a stubbed postgres engine; returns the
    kwargs the LLM client and the engine factory were constructed with.

    Callers must load the tool with `read_only=False` -- the stub engine
    can't support SQLAlchemy's real `event.listens_for` machinery that
    `_create_engine` registers in read-only mode. Read-only enforcement is
    tested against live databases at the end of this file.
    """
    engine = MagicMock()
    engine.dialect.name = "postgresql"

    with (
        patch.object(module, "create_engine", return_value=engine) as create_engine,
        patch.object(module, "ChatLiteLLM") as chat_litellm,
        patch.object(module, "SQLDatabase"),
        patch.object(module, "create_sql_agent"),
    ):
        tool._create_agent()

    return chat_litellm.call_args.kwargs, create_engine.call_args.args


def test_config_fields_supply_model_and_api_key():
    module = _load(
        db_uri=CONFIGURED_URI,
        api_key="sk-config",
        model="gemini/gemini-1.5-pro",
        read_only=False,
    )
    tool = module.NaturalLanguageToSQLTool()

    llm_kwargs, engine_args = _build_agent(module, tool)

    assert llm_kwargs == {"model": "gemini/gemini-1.5-pro", "temperature": 0, "api_key": "sk-config"}
    assert engine_args == (CONFIGURED_URI,)


@pytest.mark.parametrize("model", ["", None])
def test_blank_config_model_falls_back_to_default(model):
    module = _load(db_uri=CONFIGURED_URI, api_key="sk-config", model=model, read_only=False)
    tool = module.NaturalLanguageToSQLTool()

    llm_kwargs, _ = _build_agent(module, tool)

    assert llm_kwargs["model"] == module.DEFAULT_MODEL


def test_read_write_mode_accepts_any_dialect():
    module = _load(db_uri="sqlite://", api_key="sk-config", read_only=False)

    assert module.NaturalLanguageToSQLTool()._create_engine().dialect.name == "sqlite"


def test_read_only_mode_refuses_a_dialect_it_cannot_lock_down():
    module = _load(db_uri="sqlite://", api_key="sk-config", read_only=True)

    with pytest.raises(RuntimeError, match="sqlite"):
        module.NaturalLanguageToSQLTool()._create_engine()


def test_missing_db_uri_is_returned_as_error_in_main():
    module = _load(api_key="sk-config")

    result = module.main("how many users are there?")

    assert "db_uri" in result
    assert result.startswith("Error executing tool:")


def test_missing_api_key_is_returned_as_error_in_main():
    module = _load(db_uri=CONFIGURED_URI)

    result = module.main("how many users are there?")

    assert "api_key" in result
    assert result.startswith("Error executing tool:")


def test_unsupported_dialect_is_caught_and_returned_as_error():
    module = _load(db_uri="sqlite:///test.db", api_key="sk-config")

    result = module.main("select count(*) from users")

    assert result.startswith("Error executing tool:")
    assert "sqlite" in result


def test_third_party_failure_is_reported_without_leaking_its_content():
    module = _load(db_uri=CONFIGURED_URI, api_key="sk-config", read_only=False)

    with (
        patch.object(
            module,
            "create_engine",
            side_effect=ConnectionError(f"could not connect to {CONFIGURED_URI}"),
        ),
        patch.object(module, "ChatLiteLLM"),
    ):
        result = module.main("how many users are there?")

    assert result == "Error executing tool: ConnectionError"
    assert CONFIGURED_URI not in result


def test_stray_config_kwargs_are_absorbed_and_globals_win():
    """Regression test: python_code.global_kwargs folds user_input config
    into func_kwargs, so main() may also receive config fields as kwargs.
    The globals remain the source of truth; stray kwargs must be swallowed
    by **kwargs without a TypeError."""
    module = _load(db_uri="sqlite:///test.db", api_key="sk-config")

    result = module.main("select count(*) from users", db_uri="unused-stray-kwarg")

    assert result.startswith("Error executing tool:")


def test_the_agent_can_neither_see_nor_set_the_connection_settings():
    schema = json.loads(
        (TOOLS_ROOT / "natural_language_to_sql_tool" / "args_schema.json").read_text()
    )

    for field in ("db_uri", "api_key", "model", "read_only"):
        assert schema["properties"][field]["input_type"] == "user_input"

    assert "db_uri" in schema["required"]
    assert "api_key" in schema["required"]
    assert "model" not in schema["required"]
    assert "read_only" not in schema["required"]


def _require_docker():
    docker = pytest.importorskip("docker")
    try:
        docker.from_env().ping()
    except Exception:
        pytest.skip("Docker is not available")


@pytest.fixture(scope="module")
def postgres_uri():
    pytest.importorskip("psycopg2", reason="installed by the sandbox into this tool's own venv")
    _require_docker()
    postgres = pytest.importorskip("testcontainers.postgres")

    with postgres.PostgresContainer("postgres:17.5") as container:
        yield container.get_connection_url()


@pytest.fixture(scope="module")
def mysql_uri():
    pytest.importorskip("pymysql", reason="installed by the sandbox into this tool's own venv")
    _require_docker()
    mysql = pytest.importorskip("testcontainers.mysql")

    with mysql.MySqlContainer("mysql:8.4", dialect="pymysql") as container:
        yield container.get_connection_url()


@pytest.fixture
def item_table(postgres_uri):
    """Create a three-row table; returns a function counting its rows over a separate connection."""
    from sqlalchemy import create_engine, text

    engine = create_engine(postgres_uri)
    with engine.begin() as connection:
        connection.execute(
            text("DROP TABLE IF EXISTS item; CREATE TABLE item (id int); INSERT INTO item VALUES (1), (2), (3)")
        )

    def count():
        with engine.connect() as connection:
            return connection.execute(text("SELECT count(*) FROM item")).scalar()

    yield count
    engine.dispose()


@pytest.fixture
def mysql_schema(mysql_uri):
    """Reset the schema to a three-row table and a view on it; returns a function
    reading the schema's tables, view definitions, events and the table's row count."""
    from sqlalchemy import create_engine, text

    engine = create_engine(mysql_uri)
    with engine.begin() as connection:
        for (event_name,) in connection.execute(text("SELECT event_name FROM information_schema.events WHERE event_schema = DATABASE()")):
            connection.execute(text(f"DROP EVENT `{event_name}`"))
        for name, table_type in connection.execute(text("SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = DATABASE()")):
            connection.execute(text(f"DROP {'VIEW' if table_type == 'VIEW' else 'TABLE'} `{name}`"))
        connection.execute(text("CREATE TABLE item (id int)"))
        connection.execute(text("INSERT INTO item VALUES (1), (2), (3)"))
        connection.execute(text("CREATE VIEW item_view AS SELECT id FROM item"))

    def state():
        with engine.connect() as connection:
            return {
                query: sorted(connection.execute(text(query)).all())
                for query in (
                    "SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = DATABASE()",
                    "SELECT table_name, view_definition FROM information_schema.views WHERE table_schema = DATABASE()",
                    "SELECT event_name FROM information_schema.events WHERE event_schema = DATABASE()",
                    "SELECT count(*) FROM item",
                )
            }

    yield state
    engine.dispose()


def _query_tool(db_uri, **config):
    """Build the tool as main() does; returns the sql_db_query tool its agent calls
    and the database object the tool handed to the agent."""
    from langchain_community.tools.sql_database.tool import QuerySQLDatabaseTool

    module = _load(db_uri=db_uri, api_key="sk-config", **config)
    with patch.object(module, "create_sql_agent") as create_sql_agent:
        module.NaturalLanguageToSQLTool()._create_agent()
    database = create_sql_agent.call_args.kwargs["db"]
    return QuerySQLDatabaseTool(db=database), database, module


POSTGRES_WRITE_ATTEMPTS = {
    "plain delete": ["DELETE FROM item"],
    "read-write set in the same string": ["SET TRANSACTION READ WRITE; DELETE FROM item"],
    "session flipped by an earlier call": [
        "SET SESSION CHARACTERISTICS AS TRANSACTION READ WRITE",
        "DELETE FROM item",
    ],
    "session default flipped, then a data-modifying CTE": [
        "SELECT set_config('default_transaction_read_only', 'off', false)",
        "WITH deleted AS (DELETE FROM item RETURNING *) SELECT count(*) FROM deleted",
    ],
    "commit hidden behind a backslash in a string": [r"SELECT '\'; COMMIT; DELETE FROM item; --'"],
    "delete after a nested block comment": ["/* /* */ SELECT 1 */ DELETE FROM item"],
    "delete after a leading line comment": ["-- SELECT\nDELETE FROM item"],
}


@pytest.mark.parametrize("queries", POSTGRES_WRITE_ATTEMPTS.values(), ids=POSTGRES_WRITE_ATTEMPTS.keys())
def test_read_only_mode_keeps_every_write_attempt_out_of_postgres(postgres_uri, item_table, queries):
    query_tool, _, _ = _query_tool(postgres_uri, read_only=True)

    outputs = [query_tool.invoke(query) for query in queries]

    assert outputs[-1].startswith("Error:")
    assert item_table() == 3


@pytest.mark.parametrize("config", [{}, {"read_only": None}], ids=["unset", "none"])
def test_read_only_mode_is_the_default(postgres_uri, item_table, config):
    query_tool, database, module = _query_tool(postgres_uri, **config)

    output = query_tool.invoke("DELETE FROM item")

    assert isinstance(database, module.ReadOnlySQLDatabase)
    assert output.startswith("Error:")
    assert item_table() == 3


def test_read_only_mode_tells_the_agent_what_it_accepts(postgres_uri, item_table):
    query_tool, _, _ = _query_tool(postgres_uri, read_only=True)

    assert "accepts exactly one SELECT" in query_tool.invoke("DELETE FROM item")


def test_read_only_mode_answers_a_select(postgres_uri, item_table):
    query_tool, _, _ = _query_tool(postgres_uri, read_only=True)

    assert query_tool.invoke("SELECT count(*) FROM item") == "[(3,)]"


def test_read_write_mode_still_writes(postgres_uri, item_table):
    query_tool, _, _ = _query_tool(postgres_uri, read_only=False)

    query_tool.invoke("DELETE FROM item WHERE id = 1")

    assert item_table() == 2


MYSQL_WRITE_ATTEMPTS = {
    "version comment creating a table": "/*! CREATE TABLE pwn AS */ SELECT 1 AS id",
    "version comment replacing a view": "/*! CREATE OR REPLACE VIEW item_view AS */ SELECT 42 AS id",
    "version comment scheduling a delete": (
        "/*! CREATE EVENT wipe ON SCHEDULE AT CURRENT_TIMESTAMP DO DELETE FROM item WHERE id NOT IN ( */ SELECT 0 )"
    ),
    "plain drop": "DROP TABLE item",
    "data-modifying CTE": "WITH c AS (SELECT 1) DELETE FROM item",
}


@pytest.mark.parametrize("query", MYSQL_WRITE_ATTEMPTS.values(), ids=MYSQL_WRITE_ATTEMPTS.keys())
def test_read_only_mode_keeps_every_write_attempt_out_of_mysql(mysql_uri, mysql_schema, query):
    query_tool, _, _ = _query_tool(mysql_uri, read_only=True)
    schema_before = mysql_schema()

    output = query_tool.invoke(query)

    assert output.startswith("Error:")
    assert mysql_schema() == schema_before


@pytest.mark.parametrize("query", ["DROP TABLE item", "CREATE TABLE pwn (id int)"])
def test_mysql_connection_blocks_ddl_even_past_the_query_check(mysql_uri, mysql_schema, query):
    from sqlalchemy.exc import DBAPIError

    _, database, module = _query_tool(mysql_uri, read_only=True)
    schema_before = mysql_schema()

    with pytest.raises(DBAPIError):
        module.SQLDatabase.run(database, query)

    assert mysql_schema() == schema_before


def test_read_only_mode_answers_a_select_on_mysql(mysql_uri, mysql_schema):
    query_tool, _, _ = _query_tool(mysql_uri, read_only=True)

    assert query_tool.invoke("SELECT count(*) FROM item") == "[(3,)]"
