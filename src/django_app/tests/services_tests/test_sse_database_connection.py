import json
from uuid import uuid4

import fakeredis
import pytest
from asgiref.sync import sync_to_async
from django.db import connection
from django.utils import timezone

from tables.models.graph_models import Graph, GraphSessionMessage
from tables.models.session_models import Session
from tables.utils.mixins import SSEMixin
from tables.views import sse_views
from tables.views.sse_views import RunSessionSSEView


@pytest.fixture
def fake_async_redis(monkeypatch):
    redis_client = fakeredis.FakeAsyncRedis(decode_responses=True)
    # The SSE mixin and the view share this singleton.
    monkeypatch.setattr(sse_views.redis_service, "_async_redis_client", redis_client)
    yield redis_client


async def _database_connection_is_open() -> bool:
    # Read where the stream's queries run: Django keeps one connection per thread.
    return await sync_to_async(lambda: connection.connection is not None)()


class _StreamReportingItsConnection(SSEMixin):
    async def get_initial_data(self):
        await Session.objects.acount()
        yield {"event": "initial", "data": await _database_connection_is_open()}

    async def get_live_updates(self, pubsub):
        yield {"event": "live", "data": await _database_connection_is_open()}


class _PubSubReportingTheConnection:
    """Records whether the database connection is open when the live loop starts waiting."""

    def __init__(self):
        self.connection_open_while_waiting = None

    async def listen(self):
        self.connection_open_while_waiting = await _database_connection_is_open()
        return
        yield  # make this an async generator

    async def unsubscribe(self, *channels):
        pass

    async def close(self):
        pass


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stream_releases_its_database_connection_before_the_live_updates(
    fake_async_redis,
):
    frames = [frame async for frame in _StreamReportingItsConnection().event_stream()]

    assert frames == [
        "event: initial\n",
        "data: true\n\n",
        "event: live\n",
        "data: false\n\n",
    ]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_run_session_stream_waits_for_redis_without_a_database_connection(
    fake_async_redis, default_org
):
    graph = await sync_to_async(Graph.objects.create)(name="sse", org=default_org)
    session = await sync_to_async(Session.objects.create)(
        graph=graph, status=Session.SessionStatus.RUN, variables={}
    )
    stored_message = await sync_to_async(GraphSessionMessage.objects.create)(
        session=session,
        created_at=timezone.now(),
        execution_order=1,
        message_data={"message_type": "agent"},
        uuid=uuid4(),
    )
    view = RunSessionSSEView()
    view.kwargs = {"session_id": session.id}
    # Published while the initial data was sent, so it is read back from the database.
    view.hold_live_message(
        {
            "type": "message",
            "channel": f"session:update:{session.id}:messages",
            "data": json.dumps({"uuid": str(stored_message.uuid)}),
        }
    )
    pubsub = _PubSubReportingTheConnection()

    events = [event async for event in view.get_live_updates(pubsub)]

    assert [event["data"]["uuid"] for event in events] == [stored_message.uuid]
    assert pubsub.connection_open_while_waiting is False
