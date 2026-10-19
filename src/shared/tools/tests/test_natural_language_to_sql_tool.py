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
    `_create_engine` registers in read-only mode. Use `_engine_on` instead
    for tests about read-only enforcement itself.
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
    return [
        call.args[0] for call in connection.cursor.return_value.execute.call_args_list
    ], connection


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


@pytest.mark.parametrize("dialect", ["postgresql", "mysql"])
def test_read_only_mode_makes_every_connection_read_only(dialect):
    module = _load(db_uri=CONFIGURED_URI, api_key="sk-config", read_only=True)
    tool = module.NaturalLanguageToSQLTool()

    statements, connection = _engine_on(module, tool, dialect)

    assert statements == [module.READ_ONLY_SESSION_STATEMENTS[dialect]]
    connection.commit.assert_called_once()


def test_read_only_defaults_to_true_when_not_configured():
    module = _load(db_uri=CONFIGURED_URI, api_key="sk-config")
    tool = module.NaturalLanguageToSQLTool()

    statements, _ = _engine_on(module, tool, "postgresql")

    assert statements == [module.READ_ONLY_SESSION_STATEMENTS["postgresql"]]


def test_read_only_none_from_config_defaults_to_true():
    module = _load(db_uri=CONFIGURED_URI, api_key="sk-config", read_only=None)
    tool = module.NaturalLanguageToSQLTool()

    statements, _ = _engine_on(module, tool, "postgresql")

    assert statements == [module.READ_ONLY_SESSION_STATEMENTS["postgresql"]]


@pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
def test_read_write_mode_leaves_connections_alone(dialect):
    module = _load(db_uri=CONFIGURED_URI, api_key="sk-config", read_only=False)
    tool = module.NaturalLanguageToSQLTool()

    statements, _ = _engine_on(module, tool, dialect)

    assert statements == []


def test_read_only_mode_refuses_a_dialect_it_cannot_lock_down():
    module = _load(db_uri=CONFIGURED_URI, api_key="sk-config", read_only=True)
    tool = module.NaturalLanguageToSQLTool()

    with pytest.raises(RuntimeError, match="sqlite"):
        _engine_on(module, tool, "sqlite")


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
