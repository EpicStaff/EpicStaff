import json

import fakeredis
import pytest
from asgiref.sync import sync_to_async

from tables.models.graph_models import Graph
from tables.models.session_models import Session
from tables.views import sse_views
from tables.views.sse_views import RunSessionSSEView


class _FinitePubSub:
    """Delivers a fixed list of messages, then ends like a closed subscription."""

    def __init__(self, messages):
        self._messages = messages

    async def listen(self):
        for message in self._messages:
            yield message

    async def unsubscribe(self, *channels):
        pass

    async def close(self):
        pass


@pytest.fixture
def fake_async_redis(monkeypatch):
    redis_client = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(sse_views.redis_service, "_async_redis_client", redis_client)
    yield redis_client


def _view_for(session_id):
    view = RunSessionSSEView()
    view.kwargs = {"session_id": session_id}
    return view


def _status_message(session_id, status, status_data=None):
    return {
        "type": "message",
        "channel": f"session:update:{session_id}:status",
        "data": json.dumps(
            {
                "session_id": session_id,
                "status": status,
                "status_data": status_data or {},
            }
        ),
    }


async def _live_events(view, messages):
    return [event async for event in view.get_live_updates(_FinitePubSub(messages))]


@pytest.mark.asyncio
async def test_end_status_is_filled_with_variables_from_the_key(fake_async_redis):
    await fake_async_redis.set(
        "session:5:final_variables", json.dumps({"final_result": "hello"})
    )

    events = await _live_events(
        _view_for(5), [_status_message(5, "end", {"reason": None})]
    )

    assert events == [
        {
            "event": "status",
            "data": {
                "session_id": 5,
                "status": "end",
                "status_data": {"reason": None, "variables": {"final_result": "hello"}},
            },
        }
    ]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_end_status_falls_back_to_the_stored_session_variables(
    fake_async_redis, default_org
):
    graph = await sync_to_async(Graph.objects.create)(name="sse", org=default_org)
    session = await sync_to_async(Session.objects.create)(
        graph=graph,
        status=Session.SessionStatus.END,
        variables={},
        status_data={"variables": {"final_result": "from db"}},
    )

    events = await _live_events(
        _view_for(session.id), [_status_message(session.id, "end")]
    )

    assert [event["data"]["status_data"] for event in events] == [
        {"variables": {"final_result": "from db"}}
    ]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_end_status_without_any_stored_variables_has_no_variables(
    fake_async_redis, default_org
):
    graph = await sync_to_async(Graph.objects.create)(name="sse", org=default_org)
    session = await sync_to_async(Session.objects.create)(
        graph=graph, status=Session.SessionStatus.RUN, variables={}
    )

    events = await _live_events(
        _view_for(session.id), [_status_message(session.id, "end")]
    )

    assert [event["data"]["status_data"] for event in events] == [{}]


@pytest.mark.asyncio
async def test_other_statuses_pass_through_unchanged(fake_async_redis):
    await fake_async_redis.set(
        "session:6:final_variables", json.dumps({"final_result": "hello"})
    )

    events = await _live_events(
        _view_for(6),
        [
            _status_message(6, "run"),
            _status_message(6, "error", {"error": "node crashed"}),
        ],
    )

    assert [event["data"] for event in events] == [
        {"session_id": 6, "status": "run", "status_data": {}},
        {"session_id": 6, "status": "error", "status_data": {"error": "node crashed"}},
    ]


@pytest.mark.asyncio
async def test_another_sessions_end_status_is_dropped_without_reading_its_key(
    fake_async_redis, mocker
):
    await fake_async_redis.set(
        "session:8:final_variables", json.dumps({"final_result": "secret"})
    )
    get_spy = mocker.spy(fake_async_redis, "get")

    events = await _live_events(_view_for(7), [_status_message(8, "end")])

    assert events == []
    get_spy.assert_not_called()


@pytest.mark.asyncio
async def test_end_status_reads_the_variables_of_the_url_session_not_the_payload_one(
    fake_async_redis,
):
    await fake_async_redis.set("session:5:final_variables", json.dumps({"owner": "url"}))
    await fake_async_redis.set("session:9:final_variables", json.dumps({"owner": "payload"}))
    message_with_foreign_session_id = {
        **_status_message(9, "end"),
        "channel": "session:update:5:status",
    }

    events = await _live_events(_view_for(5), [message_with_foreign_session_id])

    assert [event["data"]["status_data"] for event in events] == [
        {"variables": {"owner": "url"}}
    ]


@pytest.mark.asyncio
async def test_graph_message_is_sent_as_received_without_a_redis_lookup(fake_async_redis):
    graph_message = {
        "session_id": 5,
        "uuid": "uuid-1",
        "name": "Agent",
        "execution_order": 1,
        "timestamp": "2026-10-05T10:00:00+00:00",
        "message_data": {"message_type": "agent", "text": "hi"},
    }
    live_message = {
        "type": "message",
        "channel": "session:update:5:messages",
        "data": json.dumps(graph_message),
    }

    events = await _live_events(_view_for(5), [live_message])

    assert events == [{"event": "messages", "data": graph_message}]
    assert await fake_async_redis.keys("*") == []


@pytest.mark.asyncio
async def test_graph_message_on_another_sessions_channel_is_not_sent(fake_async_redis):
    other_sessions_message = {
        "type": "message",
        "channel": "session:update:9:messages",
        "data": json.dumps({"session_id": 9, "uuid": "uuid-9", "message_data": {}}),
    }

    events = await _live_events(_view_for(5), [other_sessions_message])

    assert events == []
