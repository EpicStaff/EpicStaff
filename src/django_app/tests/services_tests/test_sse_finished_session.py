import asyncio
import json
import time

import fakeredis
import pytest
import pytest_asyncio
from asgiref.sync import sync_to_async

from tables.models.graph_models import Graph
from tables.models.session_models import Session
from tables.views import sse_views
from tables.views.sse_views import RunSessionSSEView

SESSION_ID = 5
# Long enough for a message sent right after the status to arrive, short for the tests.
LATE_MESSAGE_SECONDS = 0.3


@pytest.fixture(autouse=True)
def short_late_message_window(monkeypatch):
    monkeypatch.setattr(sse_views, "LATE_MESSAGE_SECONDS", LATE_MESSAGE_SECONDS)


@pytest_asyncio.fixture
async def fake_async_redis(monkeypatch):
    redis_client = fakeredis.FakeAsyncRedis(decode_responses=True)
    # The SSE mixin and the view share this singleton.
    monkeypatch.setattr(sse_views.redis_service, "_async_redis_client", redis_client)
    # An `end` status reads the session's final variables; found here, not in the database.
    await redis_client.set(f"session:{SESSION_ID}:final_variables", "{}")
    yield redis_client


class _OpenPubSub:
    """Delivers each message after its delay, then stays subscribed like a live channel."""

    def __init__(self, delayed_messages):
        self._delayed_messages = delayed_messages

    async def listen(self):
        for delay_seconds, message in self._delayed_messages:
            await asyncio.sleep(delay_seconds)
            yield message
        await asyncio.Event().wait()

    async def unsubscribe(self, *channels):
        pass

    async def close(self):
        pass


def _view_for(session_id):
    view = RunSessionSSEView()
    view.kwargs = {"session_id": session_id}
    return view


def _status_message(status):
    return {
        "type": "message",
        "channel": f"session:update:{SESSION_ID}:status",
        "data": json.dumps({"session_id": SESSION_ID, "status": status, "status_data": {}}),
    }


def _graph_message(uuid):
    return {
        "type": "message",
        "channel": f"session:update:{SESSION_ID}:messages",
        "data": json.dumps({"session_id": SESSION_ID, "uuid": uuid}),
    }


async def _live_events(delayed_messages):
    view = _view_for(SESSION_ID)
    async with asyncio.timeout(5):
        return [event async for event in view.get_live_updates(_OpenPubSub(delayed_messages))]


@pytest.mark.parametrize(
    "status",
    [
        Session.SessionStatus.END,
        Session.SessionStatus.ERROR,
        Session.SessionStatus.STOP,
        Session.SessionStatus.EXPIRED,
    ],
)
@pytest.mark.asyncio
async def test_finished_status_ends_the_stream_with_done(fake_async_redis, status):
    started_at = time.monotonic()

    events = await _live_events([(0, _status_message(status))])

    assert [event["event"] for event in events] == ["status", "done"]
    assert events[-1]["data"] == {"session_id": SESSION_ID}
    # Waited for late messages first; the margin covers Windows' ~16 ms clock ticks.
    assert time.monotonic() - started_at >= LATE_MESSAGE_SECONDS - 0.05


@pytest.mark.asyncio
async def test_message_arriving_after_the_finished_status_is_still_sent(fake_async_redis):
    events = await _live_events(
        [
            (0, _status_message(Session.SessionStatus.END)),
            (LATE_MESSAGE_SECONDS / 3, _graph_message("late-uuid")),
        ]
    )

    assert [event["event"] for event in events] == ["status", "messages", "done"]
    assert events[1]["data"]["uuid"] == "late-uuid"


@pytest.mark.asyncio
async def test_running_status_keeps_the_stream_open(fake_async_redis):
    view = _view_for(SESSION_ID)
    live_updates = view.get_live_updates(
        _OpenPubSub([(0, _status_message(Session.SessionStatus.RUN))])
    )

    assert (await anext(live_updates))["event"] == "status"
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(LATE_MESSAGE_SECONDS * 2):
            await anext(live_updates)
    await live_updates.aclose()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stream_of_an_already_finished_session_ends_after_its_replay(
    fake_async_redis, default_org
):
    graph = await sync_to_async(Graph.objects.create)(name="sse", org=default_org)
    session = await sync_to_async(Session.objects.create)(
        graph=graph, status=Session.SessionStatus.END, variables={}
    )

    async with asyncio.timeout(5):
        frames = [frame async for frame in _view_for(session.id).event_stream()]

    assert frames == [
        "event: status\n",
        f'data: {{"session_id": {session.id}, "status": "end", "status_data": {{}}}}\n\n',
        "event: done\n",
        f'data: {{"session_id": {session.id}}}\n\n',
    ]
