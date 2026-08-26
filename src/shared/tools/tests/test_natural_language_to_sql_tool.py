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
