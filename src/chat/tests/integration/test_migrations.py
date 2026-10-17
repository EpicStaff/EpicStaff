"""The migrations build exactly the models' schema on an empty database, and tear it down again.

Sync on purpose: alembic's env.py runs its own event loop.
"""

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from tests.conftest import SERVICE_ROOT


@pytest.fixture
def database(settings):
    """A database of its own, emptied for the test; yields (alembic config, psycopg url).

    Created once and kept, like the main test database, and emptied by recreating its schema:
    a DROP DATABASE on every run would force a checkpoint on the server all the tests share.
    """
    name = settings.CHAT_DB_NAME + "_migrations"
    credentials = f"{settings.CHAT_DB_USER}:{settings.CHAT_DB_PASSWORD}@{settings.CHAT_DB_HOST}:{settings.CHAT_DB_PORT}"
    with psycopg.connect(f"postgresql://{credentials}/postgres", autocommit=True) as connection:
        if not connection.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
            connection.execute(f'CREATE DATABASE "{name}"')
    url = f"postgresql://{credentials}/{name}"
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", settings.model_copy(update={"CHAT_DB_NAME": name}).database_url)
    return config, url


def _tables(connection) -> set[str]:
    return {name for (name,) in connection.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}


def _index_definitions(connection) -> dict[str, str]:
    """Each index's columns and predicate as Postgres prints them, after `USING btree`."""
    return {
        name: definition.split(" USING btree ", 1)[1]
        for name, definition in connection.execute("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'")
    }


def _statistics(connection) -> dict[str, tuple[str, list[str]]]:
    """Extended statistics objects: their kinds and columns. Alembic's check does not compare them."""
    return {
        name: (kinds, columns)
        for name, kinds, columns in connection.execute(
            "SELECT stxname, array_to_string(stxkind, ''),"
            " array(SELECT attname FROM pg_attribute WHERE attrelid = stxrelid AND attnum = ANY(stxkeys) ORDER BY attnum)"
            " FROM pg_statistic_ext WHERE stxnamespace = 'public'::regnamespace"
        )
    }


def _column_defaults(connection) -> dict[str, str]:
    """Columns with a database default; alembic's check does not compare them."""
    return {
        f"{table}.{column}": default
        for table, column, default in connection.execute(
            "SELECT table_name, column_name, column_default FROM information_schema.columns"
            " WHERE table_schema = 'public' AND column_default IS NOT NULL"
        )
    }


def _checks(connection) -> dict[str, str]:
    return dict(connection.execute("SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE contype = 'c' AND connamespace = 'public'::regnamespace").fetchall())


# The definitions a query or an invariant depends on, exactly: a partial index whose predicate drifts
# from its query's filter is silently skipped, and a CHECK is the last guard of a state rule.
KEY_INDEXES = {
    "ix_conversation_org_id_waiting": "(org_id, visitor_waiting_since, id) WHERE ((visitor_waiting_since IS NOT NULL) AND (NOT is_test))",
    "ix_conversation_org_id_human": "(org_id, handoff_at, id) WHERE ((handoff_at IS NOT NULL) AND (NOT is_test) AND (closed_at IS NULL))",
    "ix_conversation_binding_id_bot": "(binding_id, last_message_at DESC, id DESC) WHERE ((handoff_at IS NULL) AND (last_message_at IS NOT NULL) AND (NOT is_test) AND (closed_at IS NULL))",
    "ix_conversation_org_id_in_progress": "(org_id, last_message_at DESC, id DESC) WHERE ((assigned_operator_id IS NOT NULL) AND (visitor_waiting_since IS NULL) AND (last_message_at IS NOT NULL) AND (NOT is_test) AND (closed_at IS NULL))",
    # Test keeps its closed conversations: no `closed_at` test.
    "ix_conversation_org_id_test": "(org_id, last_message_at DESC, id DESC) WHERE (is_test AND (last_message_at IS NOT NULL))",
    "ix_conversation_binding_id_closed": "(binding_id, closed_at DESC, id DESC) WHERE ((closed_at IS NOT NULL) AND (last_message_at IS NOT NULL) AND (NOT is_test))",
    "ix_conversation_mine_in_progress": "(org_id, assigned_operator_id, last_message_at DESC, id DESC) WHERE ((assigned_operator_id IS NOT NULL) AND (visitor_waiting_since IS NULL) AND (last_message_at IS NOT NULL) AND (NOT is_test) AND (closed_at IS NULL))",
    "ix_conversation_mine_test": "(org_id, assigned_operator_id, last_message_at DESC, id DESC) WHERE ((assigned_operator_id IS NOT NULL) AND is_test AND (last_message_at IS NOT NULL))",
    "ix_conversation_mine_closed": "(org_id, assigned_operator_id, closed_at DESC, id DESC) WHERE ((assigned_operator_id IS NOT NULL) AND (closed_at IS NOT NULL) AND (last_message_at IS NOT NULL) AND (NOT is_test))",
    "ix_conversation_binding_id_open_activity": "(binding_id, last_message_at, id) WHERE ((closed_at IS NULL) AND (last_message_at IS NOT NULL) AND (NOT is_test) AND ((run_state)::text = 'idle'::text))",
    # conversation_id leads: a conversation's delete cascades to its events through it.
    "ix_event_conversation_seq": "(conversation_id, stream, seq)",
    "ix_conversation_org_id_signed_subject": "(org_id, lower((subject)::text) text_pattern_ops) WHERE is_signed",
    "uq_conversation_binding_subject_open": "(binding_id, subject) WHERE (closed_at IS NULL)",
    "uq_conversation_binding_visitor_number": "(binding_id, visitor_number)",
    "uq_operator_alias_binding_alias": "(binding_id, alias_key)",
    "operator_profile_pkey": "(org_id, user_id)",
}
CHECKS = {
    "ck_binding_active_contract_clean": "CHECK (((NOT is_active) OR (contract_errors = '[]'::jsonb)))",
    "ck_conversation_handoff_at_matches_mode": "CHECK ((((mode)::text = 'bot'::text) = (handoff_at IS NULL)))",
    "ck_conversation_waiting_matches_mode": "CHECK (((((mode)::text <> 'bot'::text) OR (visitor_waiting_since IS NULL)) AND (((mode)::text <> 'awaiting_human'::text) OR (visitor_waiting_since IS NOT NULL) OR (closed_at IS NOT NULL))))",
    "ck_conversation_holder_matches_mode": "CHECK ((((mode)::text = 'human'::text) = (assigned_operator_id IS NOT NULL)))",
    "ck_conversation_status_matches_closed_at": "CHECK ((((status)::text = 'closed'::text) = (closed_at IS NOT NULL)))",
    "ck_conversation_close_reason_matches_status": "CHECK ((((status)::text = 'closed'::text) = (close_reason IS NOT NULL)))",
    "ck_conversation_closed_by_only_resolved": "CHECK (((closed_by_user_id IS NOT NULL) = (NOT ((close_reason)::text IS DISTINCT FROM 'resolved'::text))))",
    "ck_conversation_closed_is_settled": "CHECK (((closed_at IS NULL) OR ((visitor_waiting_since IS NULL) AND ((run_state)::text = 'idle'::text) AND (active_run_id IS NULL) AND (active_since IS NULL) AND (late_reply_run_id IS NULL))))",
    "ck_conversation_idle_holds_no_run": "CHECK ((((run_state)::text <> 'idle'::text) OR (active_run_id IS NULL)))",
    "ck_message_action_user_only": "CHECK (((action IS NULL) OR ((role)::text = 'user'::text)))",
    "ck_message_visible_name_operator_only": "CHECK ((((role)::text = 'operator'::text) = (visible_name IS NOT NULL)))",
}
TABLES = {"alembic_version", "binding", "conversation", "visitor_number_counter", "operator_profile", "operator_alias", "daily_usage", "callback_receipt", "conversation_event", "message", "visitor_token"}


def test_head_builds_the_models_schema_from_empty_and_base_removes_it(database):
    config, url = database
    for attempt in ("from empty", "after a downgrade to base"):
        command.upgrade(config, "head")
        command.check(config)  # raises when the migrated schema and the models differ in anything alembic compares
        with psycopg.connect(url) as connection:
            assert _tables(connection) == TABLES, attempt
            indexes = _index_definitions(connection)
            assert {name: indexes.get(name) for name in KEY_INDEXES} == KEY_INDEXES, attempt
            # uq_conversation_binding_visitor_number leads with binding_id: a plain index on it is one more write per insert.
            assert "ix_conversation_binding_id" not in indexes, attempt
            assert _checks(connection) == CHECKS, attempt
            # Dependencies ('f'): a desk's rows are its org's rows, not an independent fraction of them.
            assert _statistics(connection) == {"st_conversation_binding_id_org_id": ("f", ["binding_id", "org_id"])}, attempt
            # The service writes every column itself: a forgotten value must fail, not take a default.
            assert _column_defaults(connection) == {}, attempt
        command.downgrade(config, "base")
        with psycopg.connect(url) as connection:
            assert _tables(connection) == {"alembic_version"}, attempt
            assert _statistics(connection) == {}, attempt
