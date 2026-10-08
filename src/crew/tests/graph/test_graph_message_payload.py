"""A graph message is encoded once, straight from its fields, without rebuilding flow state.

Messages carry the flow's variables and node inputs/outputs, which can be large. Sending
one must not deep-copy that state first: the message is serialized directly, and the one
JSON string is what both the graph message stream and the audit trail receive. Because
the message shares values with live flow state, that string is also the snapshot - the
audit has to record the message as it was sent, not as a node later changed it.
"""

import asyncio
import json
from dataclasses import dataclass

import fakeredis
import pytest
from langgraph.graph import StateGraph

from models.graph_models import FinishMessageData, GraphMessage, StartMessageData
from models.state import State
from src.crew.services.graph import session_audit_provider
from services.graph.events import StopEvent
from services.graph.subgraphs.decision_table_node import DecisionTableNodeSubgraph
from services.redis_service import RedisService
from src.shared.models.graph_nodes import DecisionTableNodeData
from utils.singleton_meta import SingletonMeta
from tests.graph.rebuild_counting_dict import RebuildCountingDict

SESSION_ID = 4242



@dataclass
class NestedResult:
    label: str
    score: float


class RecordingAuditWriter:
    def __init__(self):
        self.start_calls: list[dict] = []
        self.finish_calls: list[dict] = []

    async def add_start_message(self, **kwargs):
        self.start_calls.append(kwargs)

    async def add_finish_message(self, **kwargs):
        self.finish_calls.append(kwargs)


@pytest.fixture
def redis_service():
    SingletonMeta._instances.pop(RedisService, None)
    service = RedisService(host="127.0.0.1", port=6379, user="default", password="redis_password")
    service.sync_redis_client = fakeredis.FakeRedis(decode_responses=True)
    yield service
    SingletonMeta._instances.pop(RedisService, None)


@pytest.fixture
def audit_writer(monkeypatch):
    writer = RecordingAuditWriter()
    monkeypatch.setattr(session_audit_provider, "AUDIT_TRAIL_ENABLED", True)
    monkeypatch.setattr(session_audit_provider, "get_session_audit_writer", lambda: writer)
    session_audit_provider.register_session_org(SESSION_ID, org_id=7)
    session_audit_provider.register_session_flow_name(SESSION_ID, "flow")
    yield writer
    session_audit_provider.clear_session_org(SESSION_ID)
    session_audit_provider.clear_session_flow_name(SESSION_ID)


@pytest.fixture
def decision_table(redis_service):
    return DecisionTableNodeSubgraph(
        session_id=SESSION_ID,
        decision_table_node_data=DecisionTableNodeData(node_name="decide"),
        graph_builder=StateGraph(State),
        stop_event=StopEvent(),
        run_code_execution_service=None,
        redis_service=redis_service,
    )


def stream_payloads(redis_service: RedisService) -> list[dict]:
    entries = redis_service.sync_redis_client.xrange("graph.messages")
    return [json.loads(fields["payload"]) for _entry_id, fields in entries]


def graph_message(message_data) -> GraphMessage:
    return GraphMessage(
        session_id=SESSION_ID, name="decide", execution_order=1, message_data=message_data
    )


@pytest.mark.asyncio
async def test_flow_state_in_a_message_is_not_rebuilt_on_the_way_to_the_stream(
    decision_table, redis_service, audit_writer
):
    variables = RebuildCountingDict(
        customer=RebuildCountingDict(name="Ada", orders=[RebuildCountingDict(id=1)])
    )
    RebuildCountingDict.constructions = 0

    decision_table._publish_message(
        graph_message(
            FinishMessageData(output={"route": "a"}, state={"variables": variables})
        )
    )
    await asyncio.sleep(0)

    assert RebuildCountingDict.constructions == 0
    [payload] = stream_payloads(redis_service)
    assert payload["message_data"]["state"]["variables"] == {
        "customer": {"name": "Ada", "orders": [{"id": 1}]}
    }


def test_nested_dataclasses_reach_the_stream_as_objects(decision_table, redis_service):
    decision_table._publish_message(
        graph_message(FinishMessageData(output=NestedResult(label="a", score=0.5), state={}))
    )

    [payload] = stream_payloads(redis_service)
    assert payload["message_data"]["output"] == {"label": "a", "score": 0.5}


@pytest.mark.asyncio
async def test_audit_records_the_message_as_it_was_sent(
    decision_table, redis_service, audit_writer
):
    live_variables = {"counter": 1}

    decision_table._publish_message(graph_message(StartMessageData(input=live_variables)))
    # The node keeps running and changes its variables before the audit task runs.
    live_variables["counter"] = 2
    live_variables["written_later"] = True
    await asyncio.sleep(0)

    assert audit_writer.start_calls[0]["input_"] == {"counter": 1}
    [payload] = stream_payloads(redis_service)
    assert payload["message_data"]["input"] == {"counter": 1}


@pytest.mark.asyncio
async def test_stream_and_audit_receive_the_same_message(
    decision_table, redis_service, audit_writer
):
    decision_table._publish_message(
        graph_message(FinishMessageData(output={"route": "b"}, state={}))
    )
    await asyncio.sleep(0)

    [payload] = stream_payloads(redis_service)
    [finish_call] = audit_writer.finish_calls
    assert finish_call["event_id"] == payload["uuid"]
    assert finish_call["output"] == payload["message_data"]["output"] == {"route": "b"}
