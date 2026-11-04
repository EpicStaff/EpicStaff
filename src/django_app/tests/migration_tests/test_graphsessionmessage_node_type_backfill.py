"""The node_type backfill types old top-level rows from Session.graph_schema.

The column is dropped by the next migration, so the database is migrated back to the
backfill and the rows are written through that migration state's historical models.
"""

import uuid
from importlib import import_module

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

BACKFILL = ("tables", "0273_backfill_graphsessionmessage_node_type")
backfill_migration = import_module(f"tables.migrations.{BACKFILL[1]}")

# One node per list GraphData has, with the TYPE crew stores for that node.
GRAPH_SCHEMA = {
    "name": "backfill flow",
    "entrypoint": "agent #1",
    "edge_list": [{"start_key": "agent #1", "end_key": "__end_node__"}],
    "end_node": {"node_name": "__end_node__", "output_map": {}},
    "agent_node_list": [{"node_name": "agent #1"}],
    "task_node_list": [{"node_name": "task #2"}],
    "python_node_list": [{"node_name": "python #3"}],
    "knowledge_node_list": [{"node_name": "knowledge #4"}],
    "file_extractor_node_list": [{"node_name": "file_extractor #5"}],
    "key_value_node_list": [{"node_name": "key_value #6"}],
    "audio_transcription_node_list": [{"node_name": "audio #7"}],
    "subgraph_node_list": [{"node_name": "subflow #8"}],
    "decision_table_node_list": [{"node_name": "decision #9"}],
    "classification_decision_table_node_list": [{"node_name": "classification #10"}],
    "webhook_trigger_node_data_list": [{"node_name": "webhook #11"}],
    "telegram_trigger_node_data_list": [{"node_name": "telegram #12"}],
    "schedule_trigger_node_data_list": [{"node_name": "schedule #13"}],
}
EXPECTED_TYPES = {
    "__end_node__": "END",
    "agent #1": "AGENT",
    "task #2": "TASK",
    "python #3": "PYTHON",
    "knowledge #4": "KNOWLEDGE",
    "file_extractor #5": "FILE_EXTRACTOR",
    "key_value #6": "KEY_VALUE",
    "audio #7": "AUDIO_TRANSCRIPTION",
    "subflow #8": "SUBGRAPH",
    "decision #9": "DECISION_TABLE",
    "classification #10": "CLASSIFICATION_DECISION_TABLE",
    "webhook #11": "WEBHOOK_TRIGGER",
    "telegram #12": "TELEGRAM_TRIGGER",
    "schedule #13": "SCHEDULE_TRIGGER",
}


@pytest.fixture
def historical_apps():
    try:
        MigrationExecutor(connection).migrate([BACKFILL])
        yield MigrationExecutor(connection).loader.project_state([BACKFILL]).apps
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())


class _Rows:
    def __init__(self, apps):
        self.session_model = apps.get_model("tables", "Session")
        self.message_model = apps.get_model("tables", "GraphSessionMessage")

    def session(self, graph_schema, parent_session=None):
        return self.session_model.objects.create(
            status="end",
            status_updated_at=timezone.now(),
            graph_schema=graph_schema,
            parent_session=parent_session,
        )

    def message(self, session, name, node_type="", message_data=None):
        return self.message_model.objects.create(
            session=session,
            created_at=timezone.now(),
            name=name,
            message_data=message_data or {"message_type": "start"},
            node_type=node_type,
            uuid=uuid.uuid4(),
        )

    def node_type(self, message):
        return self.message_model.objects.get(pk=message.pk).node_type


@pytest.mark.django_db(transaction=True)
def test_untyped_top_level_rows_get_the_type_of_their_schema_node(historical_apps):
    rows = _Rows(historical_apps)
    session = rows.session(GRAPH_SCHEMA)
    messages = {name: rows.message(session, name) for name in EXPECTED_TYPES}
    # An empty subgraph_execution_ids list marks a top-level row as well as a missing one.
    copied_shape = rows.message(
        session, "agent #1", message_data={"message_type": "finish", "subgraph_execution_ids": []}
    )

    backfill_migration.backfill_node_types(historical_apps, None)

    assert {name: rows.node_type(message) for name, message in messages.items()} == EXPECTED_TYPES
    assert rows.node_type(copied_shape) == "AGENT"


@pytest.mark.django_db(transaction=True)
def test_rows_the_schema_cannot_type_correctly_stay_as_they_are(historical_apps):
    rows = _Rows(historical_apps)
    session = rows.session(GRAPH_SCHEMA)
    already_typed = rows.message(session, "agent #1", node_type="PYTHON")
    unknown_name = rows.message(session, "renamed #99")
    graph_end = rows.message(session, "", message_data={"message_type": "graph_end"})
    # A subflow's inner node sharing a name with a root node is a node of another graph.
    subflow_inner = rows.message(
        session, "agent #1", message_data={"message_type": "start", "subgraph_execution_ids": ["run-1"]}
    )
    # A subflow session was given its root session's schema, not its own graph's.
    child_session = rows.session(GRAPH_SCHEMA, parent_session=session)
    child_row = rows.message(child_session, "agent #1")

    backfill_migration.backfill_node_types(historical_apps, None)

    assert rows.node_type(already_typed) == "PYTHON"
    assert rows.node_type(unknown_name) == ""
    assert rows.node_type(graph_end) == ""
    assert rows.node_type(subflow_inner) == ""
    assert rows.node_type(child_row) == ""


@pytest.mark.django_db(transaction=True)
def test_every_session_is_backfilled_across_several_batches(historical_apps, monkeypatch):
    monkeypatch.setattr(backfill_migration, "SESSION_CHUNK_SIZE", 2)
    rows = _Rows(historical_apps)
    root_rows = []
    for _ in range(5):
        session = rows.session(GRAPH_SCHEMA)
        root_rows.append(rows.message(session, "agent #1"))
        # Skipped sessions sit between the paged ones, so batch boundaries fall on gaps.
        rows.session({})
        rows.session(GRAPH_SCHEMA, parent_session=session)

    backfill_migration.backfill_node_types(historical_apps, None)

    assert [rows.node_type(message) for message in root_rows] == ["AGENT"] * 5


@pytest.mark.django_db(transaction=True)
def test_session_with_empty_graph_schema_is_skipped(historical_apps):
    rows = _Rows(historical_apps)
    typed_session = rows.session(GRAPH_SCHEMA)
    typed_row = rows.message(typed_session, "agent #1")
    empty_schema_session = rows.session({})
    untouched_row = rows.message(empty_schema_session, "agent #1")

    backfill_migration.backfill_node_types(historical_apps, None)

    assert rows.node_type(typed_row) == "AGENT"
    assert rows.node_type(untouched_row) == ""
