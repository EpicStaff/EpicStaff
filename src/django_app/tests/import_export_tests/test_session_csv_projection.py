import csv
import io
import json
import uuid
from datetime import datetime

import fakeredis
import pytest

from tables.import_export.enums import EntityType
from tables.import_export.export_format_strategies import CsvExportFormatStrategy
from tables.import_export.export_tabular_projections.session import (
    SessionTabularProjection,
)
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.import_export.strategies.session import _node_types_by_name
from tables.models.graph_models import Graph, GraphSessionMessage
from tables.models.session_models import Session
from tables.services.graph_message_store import GraphMessageStore

ANSWER = "FastAPI is a modern, high-performance web framework."
USAGE = {
    "total_tokens": 740,
    "prompt_tokens": 644,
    "total_cost_usd": 0.0001542,
    "completion_tokens": 96,
    "cached_prompt_tokens": 0,
}
STATE = {"variables": {"agent_result": ANSWER}, "state_history": []}

GRAPH_SCHEMA = {
    "graph_id": 3,
    "name": "agent flow",
    "entrypoint": "agent_1 #5",
    "agent_node_list": [{"node_name": "agent_1 #5"}],
    "task_node_list": [{"node_name": "task_1 #7"}],
    "python_node_list": [{"node_name": "python_1 #8"}],
    "classification_decision_table_node_list": [{"node_name": "cdt_1 #9"}],
    "subgraph_node_list": [{"node_name": "subflow_1 #10"}],
    "key_value_node_list": [{"node_name": "kv_1 #11"}],
    "webhook_trigger_node_data_list": [{"node_name": "webhook_1 #12"}],
    "edge_list": [{"start_key": "agent_1 #5", "end_key": "__end_node__ #6"}],
    "end_node": {"node_name": "__end_node__ #6", "output_map": {}},
}


def _message(message_id, created_at, name, execution_order, message_data):
    return {
        "id": message_id,
        "session_id": 7,
        "created_at": created_at,
        "name": name,
        "execution_order": execution_order,
        "uuid": str(uuid.uuid4()),
        "message_data": message_data,
    }


# Copied from a real Agent-node session export, long texts shortened.
AGENT_SESSION_MESSAGES = [
    _message(41, "2026-10-07T12:41:02.809000Z", "agent_1 #5", 0, {"input": {}, "message_type": "start"}),
    _message(
        42,
        "2026-10-07T12:41:02.822000Z",
        "agent_1 #5",
        0,
        {
            "data": {"task": {"name": "answer", "order": 0}},
            "event": "task_start",
            "step_id": 1,
            "agent_id": 2,
            "is_final": False,
            "message_type": "agent_node_stream",
        },
    ),
    _message(
        43,
        "2026-10-07T12:41:08.297000Z",
        "agent_1 #5",
        0,
        {
            "answer": None,
            "chunks": [{"text": "FastAPI is ...", "order": 1, "source": "fastapi.txt", "similarity": 0.8042}],
            "rag_id": 1,
            "agent_id": 2,
            "rag_type": "naive",
            "token_usage": {},
            "message_type": "extracted_chunks",
            "collection_id": 1,
            "knowledge_query": "what is FastAPI?",
            "retrieved_chunks": 1,
            "rag_search_config": {"rag_type": "naive", "search_limit": 3, "similarity_threshold": 0.2},
        },
    ),
    _message(
        44,
        "2026-10-07T12:41:09.961000Z",
        "agent_1 #5",
        0,
        {
            "data": {
                "task": {"name": "answer", "order": 0},
                "message": ANSWER,
                "truncated": False,
                "iterations": 2,
                "stop_reason": "completed",
                "token_usage": USAGE,
                "tool_invocations": 1,
            },
            "event": "task_finish",
            "step_id": 2,
            "agent_id": 2,
            "is_final": False,
            "message_type": "agent_node_stream",
        },
    ),
    _message(
        45,
        "2026-10-07T12:41:09.967000Z",
        "agent_1 #5",
        0,
        {
            "state": STATE,
            "output": {
                "tasks": [{"name": "answer", "order": 0, "message": ANSWER}],
                "message": ANSWER,
                "iterations": 2,
                "stop_reason": "completed",
                "token_usage": USAGE,
                "tool_invocations": 1,
                "structured_output": None,
            },
            "message_type": "finish",
            "additional_data": {},
        },
    ),
    _message(46, "2026-10-07T12:41:09.971000Z", "__end_node__ #6", 1, {"input": {}, "message_type": "start"}),
    _message(47, "2026-10-07T12:41:09.971000Z", "__end_node__ #6", 1, {"context": {"agent_result": ANSWER}}),
    # Same created_at as its start row, and placed before it on purpose.
    _message(
        48,
        "2026-10-07T12:41:09.971000Z",
        "__end_node__ #6",
        1,
        {
            "state": STATE,
            "output": {"context": {"agent_result": ANSWER}},
            "message_type": "finish",
            "additional_data": {},
        },
    ),
    _message(
        49,
        "2026-10-07T12:41:09.985000Z",
        "",
        0,
        {"message_type": "graph_end", "end_node_result": {"context": {"agent_result": ANSWER}}},
    ),
]

OTHER_NODE_MESSAGES = [
    _message(
        60,
        "2026-10-07T13:00:00.000000Z",
        "task_1 #7",
        2,
        {
            "message_type": "task_node_stream",
            "event": "tool_call",
            "step_id": 1,
            "is_final": False,
            "agent_id": 4,
            "data": {
                "id": "call_1",
                "name": "web_search",
                "arguments": {"query": "fastapi"},
                "truncated": False,
                "token_usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
                "task": {"name": "research", "order": 0},
            },
        },
    ),
    _message(
        61,
        "2026-10-07T13:00:00.100000Z",
        "task_1 #7",
        2,
        {
            "message_type": "task_node_stream",
            "event": "tool_result",
            "step_id": 2,
            "is_final": False,
            "agent_id": 4,
            "data": {
                "tool_call_id": "call_1",
                "name": "web_search",
                "content": "timeout",
                "is_error": True,
                "truncated": False,
                "token_usage": {},
                "task": {"name": "research", "order": 0},
            },
        },
    ),
    _message(
        62,
        "2026-10-07T13:00:01.000000Z",
        "task_1 #7",
        2,
        {
            "state": STATE,
            "output": {
                "message": "plain text",
                "structured_output": {"answer": 42},
                "token_usage": USAGE,
                "stop_reason": "schema_satisfied",
                "iterations": 3,
                "tool_invocations": 1,
            },
            "message_type": "finish",
            "additional_data": {},
        },
    ),
    _message(
        63,
        "2026-10-07T13:00:02.000000Z",
        "python_1 #8",
        3,
        {
            "message_type": "python",
            "python_code_execution_data": {
                "execution_id": "exec-1",
                "result_data": {"total": 5},
                "stderr": "",
                "stdout": "computed\n",
                "returncode": 0,
            },
        },
    ),
    _message(
        64,
        "2026-10-07T13:00:02.500000Z",
        "python_1 #8",
        4,
        {
            "message_type": "python",
            "python_code_execution_data": {
                "execution_id": "exec-2",
                "result_data": None,
                "stderr": "ZeroDivisionError",
                "stdout": "",
                "returncode": 1,
            },
        },
    ),
    _message(
        65,
        "2026-10-07T13:00:02.600000Z",
        "python_1 #8",
        4,
        {"message_type": "error", "details": "ZeroDivisionError"},
    ),
    _message(
        66,
        "2026-10-07T13:00:02.700000Z",
        "",
        0,
        {"message_type": "error", "error": "graph crashed"},
    ),
    _message(
        67,
        "2026-10-07T13:00:03.000000Z",
        "cdt_1 #9",
        5,
        {
            "message_type": "classification_prompt",
            "prompt_id": "triage",
            "prompt_text": "Classify: refund please",
            "raw_response": "{'label': 'refund'}",
            "parsed_result": {"label": "refund"},
            "result_variable": "label",
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 5,
                "total_tokens": 25,
                "successful_requests": 1,
                "cached_prompt_tokens": 0,
                "total_cost_usd": 0.00002,
            },
        },
    ),
    _message(
        68,
        "2026-10-07T13:00:03.100000Z",
        "cdt_1 #9",
        5,
        {"message_type": "condition_group", "group_name": "refund", "result": True, "expression": "label == 'refund'"},
    ),
    _message(
        69,
        "2026-10-07T13:00:04.000000Z",
        "subflow_1 #10",
        6,
        {
            "message_type": "subgraph_start",
            "state": STATE,
            "input": {"query": "x"},
            "subgraph_id": 12,
            "subgraph_execution_id": "sub-1",
        },
    ),
    _message(
        70,
        "2026-10-07T13:00:04.200000Z",
        "inner_python #3",
        0,
        {"message_type": "python_stream", "text": "Executing 'inner_python #3'...", "is_final": False},
    ),
    _message(
        71,
        "2026-10-07T13:00:05.250000Z",
        "subflow_1 #10",
        6,
        {"message_type": "subgraph_finish", "state": STATE, "output": {"result": "ok"}, "subgraph_execution_id": "sub-1"},
    ),
    _message(
        72,
        "2026-10-07T13:00:06.000000Z",
        "kv_1 #11",
        7,
        {
            "message_type": "key_value",
            "mode": "read",
            "table_id": 1,
            "table_name": "prefs",
            "entries": [{"key": "lang", "path": "variables.lang", "found": True, "value": "en"}],
            "deleted_count": None,
        },
    ),
]


def _session_item(messages, session_id=7):
    return {
        "session": {
            "id": session_id,
            "status": "end",
            "graph": 3,
            "graph_name": "agent flow",
            "node_types": _node_types_by_name(GRAPH_SCHEMA),
            "principal": {"kind": "user", "user": 2, "api_key": None, "email": "admin@example.com"},
        },
        "messages": [{**message, "session_id": session_id} for message in messages],
    }


def _render_csv(data) -> list[dict]:
    response = CsvExportFormatStrategy(SessionTabularProjection()).render(
        data, EntityType.SESSION, "session", "7"
    )
    reader = csv.DictReader(io.StringIO(response.content.decode()))
    assert reader.fieldnames == SessionTabularProjection.FIELDS
    return list(reader)


def _rows_by_message_id(messages) -> dict[str, dict]:
    rows = _render_csv({EntityType.SESSION: [_session_item(messages)]})
    return {row["message_id"]: row for row in rows}


def test_agent_session_rows():
    rows = _rows_by_message_id(AGENT_SESSION_MESSAGES)

    assert list(rows) == [str(message["id"]) for message in AGENT_SESSION_MESSAGES]
    for row in rows.values():
        assert row["session_id"] == "7"
        assert row["flow_id"] == "3"
        assert row["flow_name"] == "agent flow"
        assert row["session_status"] == "end"
        assert row["started_by_type"] == "user"
        assert row["started_by"] == "admin@example.com"
        assert "state_history" not in row["details"]

    start = rows["41"]
    assert (start["node_name"], start["node_type"], start["message_type"]) == ("agent_1 #5", "agent", "start")
    assert start["input"] == "{}"
    assert start["duration_ms"] == ""

    task_start = rows["42"]
    assert (task_start["event"], task_start["task_name"]) == ("task_start", "answer")
    assert json.loads(task_start["details"]) == {"step_id": 1, "agent_id": 2, "is_final": False}

    chunks = rows["43"]
    assert chunks["input"] == "what is FastAPI?"
    details = json.loads(chunks["details"])
    assert details["retrieved_chunks"] == 1
    assert details["chunks"][0]["source"] == "fastapi.txt"
    assert "answer" not in details and "token_usage" not in details

    task_finish = rows["44"]
    assert task_finish["event"] == "task_finish"
    assert task_finish["output"] == ANSWER
    assert (task_finish["stop_reason"], task_finish["iterations"], task_finish["tool_invocations"]) == (
        "completed",
        "2",
        "1",
    )
    assert (task_finish["prompt_tokens"], task_finish["cost_usd"]) == ("644", "0.0001542")

    finish = rows["45"]
    assert finish["output"] == ANSWER
    assert finish["stop_reason"] == "completed"
    assert (finish["prompt_tokens"], finish["completion_tokens"], finish["total_tokens"]) == ("644", "96", "740")
    assert finish["cached_prompt_tokens"] == "0"
    assert finish["cost_usd"] == "0.0001542"
    assert finish["duration_ms"] == "7158"
    assert json.loads(finish["details"]) == {"tasks": [{"name": "answer", "order": 0, "message": ANSWER}]}

    assert rows["46"]["node_type"] == "end"
    end_output = rows["47"]
    assert end_output["message_type"] == "end_output"
    assert json.loads(end_output["output"]) == {"context": {"agent_result": ANSWER}}
    assert end_output["details"] == ""

    end_finish = rows["48"]
    assert json.loads(end_finish["output"]) == {"context": {"agent_result": ANSWER}}
    assert end_finish["duration_ms"] == "0"

    graph_end = rows["49"]
    assert (graph_end["message_type"], graph_end["node_type"]) == ("graph_end", "")
    assert json.loads(graph_end["output"]) == {"context": {"agent_result": ANSWER}}


def test_end_node_duration_does_not_depend_on_row_order():
    end_start, end_output, end_finish = AGENT_SESSION_MESSAGES[5:8]

    rows = _rows_by_message_id([end_finish, end_output, end_start])

    assert rows["48"]["duration_ms"] == "0"


def test_other_node_message_rows():
    rows = _rows_by_message_id(OTHER_NODE_MESSAGES)

    tool_call = rows["60"]
    assert (tool_call["node_type"], tool_call["event"], tool_call["task_name"]) == ("task", "tool_call", "research")
    assert tool_call["tool_name"] == "web_search"
    assert json.loads(tool_call["tool_arguments"]) == {"query": "fastapi"}
    assert (tool_call["prompt_tokens"], tool_call["total_tokens"]) == ("10", "12")
    assert json.loads(tool_call["details"])["id"] == "call_1"

    tool_result = rows["61"]
    assert (tool_result["tool_name"], tool_result["tool_result"], tool_result["error"]) == (
        "web_search",
        "timeout",
        "timeout",
    )

    task_finish = rows["62"]
    assert json.loads(task_finish["output"]) == {"answer": 42}
    assert json.loads(task_finish["details"]) == {"message": "plain text"}
    assert task_finish["stop_reason"] == "schema_satisfied"

    python_ok = rows["63"]
    assert python_ok["node_type"] == "python"
    assert json.loads(python_ok["output"]) == {"total": 5}
    assert python_ok["error"] == ""
    assert json.loads(python_ok["details"]) == {"execution_id": "exec-1", "stdout": "computed\n", "returncode": 0}

    python_failed = rows["64"]
    assert python_failed["error"] == "ZeroDivisionError"
    assert python_failed["output"] == ""

    assert rows["65"]["error"] == "ZeroDivisionError"
    assert rows["66"]["error"] == "graph crashed"

    classification = rows["67"]
    assert classification["node_type"] == "classification_decision_table"
    assert classification["input"] == "Classify: refund please"
    assert json.loads(classification["output"]) == {"label": "refund"}
    assert (classification["total_tokens"], classification["cost_usd"]) == ("25", "0.00002")
    assert json.loads(classification["details"]) == {
        "prompt_id": "triage",
        "raw_response": "{'label': 'refund'}",
        "result_variable": "label",
    }

    condition = rows["68"]
    assert json.loads(condition["details"]) == {
        "group_name": "refund",
        "result": True,
        "expression": "label == 'refund'",
    }

    subflow_start = rows["69"]
    assert subflow_start["node_type"] == "subgraph"
    assert json.loads(subflow_start["input"]) == {"query": "x"}
    assert json.loads(subflow_start["details"]) == {"subgraph_id": 12, "subgraph_execution_id": "sub-1"}

    inner_node = rows["70"]
    assert (inner_node["message_type"], inner_node["node_type"]) == ("python_stream", "")
    assert inner_node["output"] == "Executing 'inner_python #3'..."

    subflow_finish = rows["71"]
    assert json.loads(subflow_finish["output"]) == {"result": "ok"}
    assert subflow_finish["duration_ms"] == "1250"

    key_value = rows["72"]
    assert key_value["node_type"] == "key_value"
    assert json.loads(key_value["details"])["entries"][0]["value"] == "en"


@pytest.mark.django_db
def test_exported_session_csv_carries_flow_and_node_type(default_org):
    graph = Graph.objects.create(name="csv flow", org=default_org)
    session = Session.objects.create(graph=graph, status=Session.SessionStatus.END, graph_schema=GRAPH_SCHEMA)
    for message in AGENT_SESSION_MESSAGES[:1] + AGENT_SESSION_MESSAGES[4:5]:
        GraphSessionMessage.objects.create(
            session=session,
            created_at=datetime.fromisoformat(message["created_at"]),
            name=message["name"],
            execution_order=message["execution_order"],
            message_data=message["message_data"],
            uuid=uuid.uuid4(),
        )

    data = ExportService(entity_registry).export_entities(EntityType.SESSION, [session.id])
    start, finish = _render_csv(data)

    assert (start["flow_id"], start["flow_name"], start["session_status"]) == (str(graph.id), "csv flow", "end")
    assert (start["node_type"], finish["node_type"]) == ("agent", "agent")
    [exported] = data[EntityType.SESSION]
    assert "graph_schema" not in exported["session"]
    assert exported["session"]["node_types"]["__end_node__ #6"] == "end"
    assert finish["duration_ms"] == "7158"
    assert finish["cost_usd"] == "0.0001542"


def test_same_node_twice_gets_one_duration_per_execution():
    def run(first_id, execution_order, started, finished):
        return [
            _message(first_id, started, "python_1 #8", execution_order, {"message_type": "start", "input": {}}),
            _message(
                first_id + 1,
                finished,
                "python_1 #8",
                execution_order,
                {"message_type": "finish", "output": 1, "state": STATE},
            ),
        ]

    rows = _rows_by_message_id(
        run(80, 1, "2026-10-07T13:00:00.000000Z", "2026-10-07T13:00:00.300000Z")
        + run(82, 2, "2026-10-07T13:00:01.000000Z", "2026-10-07T13:00:01.050000Z")
    )

    assert (rows["81"]["duration_ms"], rows["83"]["duration_ms"]) == ("300", "50")


def test_finish_without_start_has_no_duration():
    rows = _rows_by_message_id(AGENT_SESSION_MESSAGES[4:5])

    assert rows["45"]["duration_ms"] == ""


def test_old_rows_without_stored_node_type_fall_back_to_graph_schema():
    rows = _rows_by_message_id(AGENT_SESSION_MESSAGES[:1])

    assert rows["41"]["node_type"] == "agent"


def test_stored_node_type_wins_and_spreads_to_untyped_rows_of_the_same_node():
    start = {**AGENT_SESSION_MESSAGES[0], "name": "inner_agent #2", "node_type": "AGENT"}
    stream = {**AGENT_SESSION_MESSAGES[1], "name": "inner_agent #2", "node_type": ""}
    # Stored type beats the graph_schema type ("python") for the same name.
    python_start = {**OTHER_NODE_MESSAGES[3], "node_type": "WEBHOOK_TRIGGER"}

    rows = _rows_by_message_id([start, stream, python_start])

    assert (rows["41"]["node_type"], rows["42"]["node_type"]) == ("agent", "agent")
    assert rows["63"]["node_type"] == "webhook_trigger"


def test_cost_is_a_fixed_decimal():
    usage = {**USAGE, "total_cost_usd": 1.4999999999999999e-05}
    finish = AGENT_SESSION_MESSAGES[4]
    message = {**finish, "message_data": {**finish["message_data"], "output": {**finish["message_data"]["output"], "token_usage": usage}}}

    rows = _rows_by_message_id([message])

    assert rows["45"]["cost_usd"] == "0.000015"


def _subflow_copy(message, message_id):
    return {**message, "id": message_id, "uuid": str(uuid.uuid4())}


def test_subflow_copies_are_dropped_when_the_original_is_exported():
    start, finish = AGENT_SESSION_MESSAGES[0], AGENT_SESSION_MESSAGES[4]
    root = _session_item([start, finish])
    child = _session_item([_subflow_copy(finish, 90)], session_id=8)
    grandchild = _session_item([_subflow_copy(finish, 91)], session_id=9)

    # Item order must not matter, and the middle child may be missing.
    together = _render_csv({EntityType.SESSION: [grandchild, child, root]})
    root_and_grandchild = _render_csv({EntityType.SESSION: [grandchild, root]})
    child_alone = _render_csv({EntityType.SESSION: [child]})

    assert [row["message_id"] for row in together] == ["41", "45"]
    assert [row["message_id"] for row in root_and_grandchild] == ["41", "45"]
    assert [(row["session_id"], row["message_id"]) for row in child_alone] == [("8", "90")]


def test_fan_out_child_rows_survive_next_to_their_parent():
    root = _session_item(AGENT_SESSION_MESSAGES[:1])
    # A fan-out child is its own run: same node names, its own timestamps.
    fan_out_start = {**AGENT_SESSION_MESSAGES[0], "id": 95, "created_at": "2026-10-07T12:41:03.100000Z"}
    fan_out = _session_item([fan_out_start], session_id=8)

    rows = _render_csv({EntityType.SESSION: [root, fan_out]})

    assert [(row["session_id"], row["message_id"]) for row in rows] == [("7", "41"), ("8", "95")]


def test_parent_and_subflow_nodes_with_the_same_name_keep_their_own_type():
    def message(message_id, message_type, node_type, execution_ids):
        data = {"message_type": message_type, "input": {}, "subgraph_execution_ids": execution_ids}
        return {**_message(message_id, "2026-10-07T13:00:00.000000Z", "shared #1", 0, data), "node_type": node_type}

    rows = _rows_by_message_id(
        [
            message(1, "start", "PYTHON", []),
            message(2, "python_stream", "", []),
            message(3, "start", "AGENT", ["sub-1"]),
            message(4, "extracted_chunks", "", ["sub-1"]),
        ]
    )

    assert [rows[message_id]["node_type"] for message_id in "1234"] == ["python", "python", "agent", "agent"]


@pytest.mark.django_db
def test_root_export_drops_subflow_copies_and_child_copy_keeps_node_type(default_org):
    root_graph = Graph.objects.create(name="root flow", org=default_org)
    child_graph = Graph.objects.create(name="child flow", org=default_org)
    root = Session.objects.create(graph=root_graph, status=Session.SessionStatus.END, graph_schema=GRAPH_SCHEMA)
    execution_id = str(uuid.uuid4())
    inner_finish = {
        "message_type": "finish",
        "state": STATE,
        "output": {"message": ANSWER, "token_usage": USAGE, "stop_reason": "completed"},
        "subgraph_execution_ids": [execution_id],
    }
    for node_type, message_data in [
        ("", {"message_type": "subgraph_start", "input": {}, "subgraph_id": child_graph.id, "subgraph_execution_id": execution_id}),
        ("AGENT", inner_finish),
        ("", {"message_type": "subgraph_finish", "output": {}, "subgraph_execution_id": execution_id}),
    ]:
        GraphSessionMessage.objects.create(
            session=root,
            created_at=datetime.fromisoformat("2026-10-07T13:00:00.000000Z"),
            name="inner_agent #2",
            message_data=message_data,
            node_type=node_type,
            uuid=uuid.uuid4(),
            parent_subgraph_execution_id=(message_data.get("subgraph_execution_ids") or [None])[0],
        )
    GraphMessageStore(fakeredis.FakeRedis()).create_subgraph_sessions(root.id)
    child = Session.objects.get(parent_session=root)
    export = ExportService(entity_registry).export_entities

    root_rows = _render_csv(export(EntityType.SESSION, [root.id]))
    [child_row] = _render_csv(export(EntityType.SESSION, [child.id]))

    assert {row["session_id"] for row in root_rows} == {str(root.id)}
    assert len(root_rows) == 3
    assert (child_row["session_id"], child_row["flow_name"]) == (str(child.id), "child flow")
    assert (child_row["node_type"], child_row["cost_usd"]) == ("agent", "0.0001542")
