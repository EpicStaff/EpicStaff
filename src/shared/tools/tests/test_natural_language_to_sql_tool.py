from unittest.mock import MagicMock, patch

import pytest

from conftest import load_tool_main

# natural_language_to_sql_tool/main.py imports sqlalchemy at module level. Per
# tool_data.yaml's requirements.txt, sqlalchemy (and langchain/litellm) are
# installed into this tool's own dedicated venv by the sandbox at execution
# time, not into any service venv — skip cleanly instead of failing when
# running these tests outside that venv.
pytest.importorskip(
    "sqlalchemy",
    reason="installed by the sandbox into this tool's own venv, not a service venv",
)

POSTGRES_URI = "postgresql+psycopg2://user:pass@localhost/db"


def _tool(**variables):
    module = load_tool_main("natural_language_to_sql_tool")
    module.state = {"variables": {"DB_URI": POSTGRES_URI, "READ_ONLY": False, **variables}}
    return module, module.NaturalLanguageToSQLTool()


def _engine_on(module, tool, dialect: str):
    """Create the tool's engine against a database of `dialect`; returns the
    statements a new connection runs before the agent gets it."""
    engine = MagicMock()
    engine.dialect.name = dialect
    connect_listeners = []

    def listens_for(target, identifier):
        assert (target, identifier) == (engine, "connect")
        return lambda listener: connect_listeners.append(listener) or listener

    with (
        patch.object(module, "create_engine", return_value=engine),
        patch.object(module.event, "listens_for", side_effect=listens_for),
    ):
        tool._create_engine()

    connection = MagicMock()
    for listener in connect_listeners:
        listener(connection, None)
    return [call.args[0] for call in connection.cursor.return_value.execute.call_args_list], connection


@pytest.mark.parametrize(
    ("dialect", "statement"),
    [
        ("postgresql", "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY"),
        ("mysql", "SET SESSION TRANSACTION READ ONLY"),
    ],
)
def test_read_only_mode_makes_every_connection_read_only(dialect, statement):
    module, tool = _tool(OPENAI_API_KEY="sk-test", READ_ONLY=True)

    statements, connection = _engine_on(module, tool, dialect)

    assert statements == [statement]
    connection.commit.assert_called_once()


def test_read_only_mode_refuses_a_dialect_it_cannot_lock_down():
    module, tool = _tool(OPENAI_API_KEY="sk-test", READ_ONLY=True)

    with pytest.raises(RuntimeError, match="sqlite"):
        _engine_on(module, tool, "sqlite")


@pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
def test_read_write_mode_leaves_connections_alone(dialect):
    module, tool = _tool(OPENAI_API_KEY="sk-test", READ_ONLY=False)

    statements, _ = _engine_on(module, tool, dialect)

    assert statements == []


@pytest.mark.parametrize(
    ("variables", "expected_model", "expected_key"),
    [
        ({"OPENAI_API_KEY": "sk-legacy"}, "gpt-4o-mini", "sk-legacy"),
        ({"API_KEY": "sk-new", "OPENAI_API_KEY": "sk-legacy"}, "gpt-4o-mini", "sk-new"),
        ({"OPENAI_API_KEY": "sk-test", "MODEL": "anthropic/claude-3-5-sonnet-20241022"},
         "anthropic/claude-3-5-sonnet-20241022", "sk-test"),
    ],
    ids=["legacy-key-default-model", "api-key-wins", "custom-model"],
)
def test_the_agent_llm_gets_the_configured_model_and_key(variables, expected_model, expected_key):
    module, tool = _tool(**variables)
    engine = MagicMock()
    engine.dialect.name = "postgresql"

    with (
        patch.object(module, "create_engine", return_value=engine),
        patch.object(module, "ChatLiteLLM") as chat_litellm,
        patch.object(module, "SQLDatabase"),
        patch.object(module, "create_sql_agent"),
    ):
        tool._create_agent()

    chat_litellm.assert_called_once_with(model=expected_model, temperature=0, api_key=expected_key)


def test_missing_api_key_is_refused():
    with pytest.raises(RuntimeError, match="API_KEY"):
        _tool()
