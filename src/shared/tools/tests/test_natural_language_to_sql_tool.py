from unittest.mock import MagicMock, patch

import pytest

from conftest import load_tool_main


def _make_tool(module, db_uri: str, read_only: bool):
    module.state = {
        "variables": {
            "DB_URI": db_uri,
            "OPENAI_API_KEY": "sk-test",
            "READ_ONLY": read_only,
        }
    }
    return module.NaturalLanguageToSQLTool()


def _fake_engine(dialect_name: str) -> MagicMock:
    engine = MagicMock()
    engine.dialect.name = dialect_name
    return engine


class TestNaturalLanguageToSQLToolReadOnlyPostgres:
    def test_read_only_postgres_registers_listener_that_sets_read_only(self):
        module = load_tool_main("natural_language_to_sql_tool")
        tool = _make_tool(
            module, "postgresql+psycopg2://user:pass@localhost/db", read_only=True
        )
        fake_engine = _fake_engine("postgresql")

        captured_listener = {}

        def fake_listens_for(target, identifier):
            assert target is fake_engine
            assert identifier == "connect"

            def decorator(fn):
                captured_listener["fn"] = fn
                return fn

            return decorator

        with (
            patch.object(module, "create_engine", return_value=fake_engine),
            patch.object(module.event, "listens_for", side_effect=fake_listens_for),
        ):
            engine = tool._create_engine()

        assert engine is fake_engine
        assert "fn" in captured_listener

        fake_cursor = MagicMock()
        fake_connection = MagicMock()
        fake_connection.cursor.return_value = fake_cursor

        captured_listener["fn"](fake_connection, None)

        fake_cursor.execute.assert_called_once_with(
            "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY"
        )
        fake_cursor.close.assert_called_once()
        fake_connection.commit.assert_called_once()


class TestNaturalLanguageToSQLToolReadOnlyMySQL:
    def test_read_only_mysql_registers_listener_that_sets_read_only(self):
        module = load_tool_main("natural_language_to_sql_tool")
        tool = _make_tool(
            module, "mysql+pymysql://user:pass@localhost/db", read_only=True
        )
        fake_engine = _fake_engine("mysql")

        captured_listener = {}

        def fake_listens_for(target, identifier):
            assert target is fake_engine
            assert identifier == "connect"

            def decorator(fn):
                captured_listener["fn"] = fn
                return fn

            return decorator

        with (
            patch.object(module, "create_engine", return_value=fake_engine),
            patch.object(module.event, "listens_for", side_effect=fake_listens_for),
        ):
            engine = tool._create_engine()

        assert engine is fake_engine
        assert "fn" in captured_listener

        fake_cursor = MagicMock()
        fake_connection = MagicMock()
        fake_connection.cursor.return_value = fake_cursor

        captured_listener["fn"](fake_connection, None)

        fake_cursor.execute.assert_called_once_with("SET SESSION TRANSACTION READ ONLY")
        fake_cursor.close.assert_called_once()
        fake_connection.commit.assert_called_once()


class TestNaturalLanguageToSQLToolUnsupportedDialect:
    def test_read_only_unsupported_dialect_raises_runtime_error(self):
        module = load_tool_main("natural_language_to_sql_tool")
        tool = _make_tool(module, "sqlite:///:memory:", read_only=True)
        fake_engine = _fake_engine("sqlite")

        with patch.object(module, "create_engine", return_value=fake_engine):
            with pytest.raises(RuntimeError) as exc_info:
                tool._create_engine()

        assert "sqlite" in str(exc_info.value)


class TestNaturalLanguageToSQLToolModelAndApiKey:
    def test_model_defaults_to_gpt_4o_mini_when_not_set(self):
        module = load_tool_main("natural_language_to_sql_tool")
        module.state = {
            "variables": {
                "DB_URI": "postgresql+psycopg2://user:pass@localhost/db",
                "OPENAI_API_KEY": "sk-test",
                "READ_ONLY": False,
            }
        }
        tool = module.NaturalLanguageToSQLTool()

        assert tool.model == "gpt-4o-mini"

    def test_model_defaults_to_gpt_4o_mini_and_is_passed_to_chatlitellm(self):
        module = load_tool_main("natural_language_to_sql_tool")
        module.state = {
            "variables": {
                "DB_URI": "postgresql+psycopg2://user:pass@localhost/db",
                "OPENAI_API_KEY": "sk-test",
                "READ_ONLY": False,
            }
        }
        tool = module.NaturalLanguageToSQLTool()
        fake_engine = _fake_engine("postgresql")

        with (
            patch.object(module, "create_engine", return_value=fake_engine),
            patch.object(module, "ChatLiteLLM") as fake_chat_litellm,
            patch.object(module, "SQLDatabase") as fake_sql_database,
            patch.object(module, "create_sql_agent") as fake_create_sql_agent,
        ):
            fake_sql_database.return_value.dialect = "postgresql"
            tool._create_agent()

        fake_chat_litellm.assert_called_once_with(
            model="gpt-4o-mini", temperature=0, api_key="sk-test"
        )

    def test_non_default_model_is_passed_through_to_chatlitellm(self):
        module = load_tool_main("natural_language_to_sql_tool")
        module.state = {
            "variables": {
                "DB_URI": "postgresql+psycopg2://user:pass@localhost/db",
                "MODEL": "anthropic/claude-3-5-sonnet-20241022",
                "OPENAI_API_KEY": "sk-test",
                "READ_ONLY": False,
            }
        }
        tool = module.NaturalLanguageToSQLTool()
        fake_engine = _fake_engine("postgresql")

        with (
            patch.object(module, "create_engine", return_value=fake_engine),
            patch.object(module, "ChatLiteLLM") as fake_chat_litellm,
            patch.object(module, "SQLDatabase") as fake_sql_database,
            patch.object(module, "create_sql_agent") as fake_create_sql_agent,
        ):
            fake_sql_database.return_value.dialect = "postgresql"
            tool._create_agent()

        fake_chat_litellm.assert_called_once_with(
            model="anthropic/claude-3-5-sonnet-20241022",
            temperature=0,
            api_key="sk-test",
        )

    def test_api_key_falls_back_to_openai_api_key(self):
        module = load_tool_main("natural_language_to_sql_tool")
        module.state = {
            "variables": {
                "DB_URI": "postgresql+psycopg2://user:pass@localhost/db",
                "OPENAI_API_KEY": "sk-legacy",
                "READ_ONLY": False,
            }
        }
        tool = module.NaturalLanguageToSQLTool()

        assert tool.api_key == "sk-legacy"

    def test_api_key_takes_precedence_over_openai_api_key(self):
        module = load_tool_main("natural_language_to_sql_tool")
        module.state = {
            "variables": {
                "DB_URI": "postgresql+psycopg2://user:pass@localhost/db",
                "API_KEY": "sk-new",
                "OPENAI_API_KEY": "sk-legacy",
                "READ_ONLY": False,
            }
        }
        tool = module.NaturalLanguageToSQLTool()

        assert tool.api_key == "sk-new"

    def test_missing_both_api_key_variables_raises_runtime_error(self):
        module = load_tool_main("natural_language_to_sql_tool")
        module.state = {
            "variables": {
                "DB_URI": "postgresql+psycopg2://user:pass@localhost/db",
                "READ_ONLY": False,
            }
        }

        with pytest.raises(RuntimeError) as exc_info:
            module.NaturalLanguageToSQLTool()

        assert "API_KEY" in str(exc_info.value)


class TestNaturalLanguageToSQLToolReadWrite:
    def test_read_write_mode_registers_no_read_only_listener(self):
        module = load_tool_main("natural_language_to_sql_tool")
        tool = _make_tool(
            module, "postgresql+psycopg2://user:pass@localhost/db", read_only=False
        )
        fake_engine = _fake_engine("postgresql")

        with (
            patch.object(module, "create_engine", return_value=fake_engine),
            patch.object(module.event, "listens_for") as fake_listens_for,
        ):
            engine = tool._create_engine()

        assert engine is fake_engine
        fake_listens_for.assert_not_called()

    def test_read_write_mode_does_not_raise_for_unsupported_dialect(self):
        module = load_tool_main("natural_language_to_sql_tool")
        tool = _make_tool(module, "sqlite:///:memory:", read_only=False)
        fake_engine = _fake_engine("sqlite")

        # Should not raise: the dialect-support check is only enforced when
        # read_only is True.
        with patch.object(module, "create_engine", return_value=fake_engine):
            engine = tool._create_engine()

        assert engine is fake_engine
