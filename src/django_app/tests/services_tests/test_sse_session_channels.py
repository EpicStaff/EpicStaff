import asyncio
import json

import fakeredis
import pytest

from tables.views import sse_views
from tables.views.flow_assistant_views import FlowAssistantStreamView
from tables.views.sse_views import RunSessionSSEView

SESSION_ID = 101
OTHER_SESSION_ID = 102


@pytest.fixture
def fake_async_redis(monkeypatch):
    redis_client = fakeredis.FakeAsyncRedis(decode_responses=True)
    # The SSE mixin and the view share this singleton.
    monkeypatch.setattr(sse_views.redis_service, "_async_redis_client", redis_client)
    yield redis_client


def _run_session_view(session_id):
    view = RunSessionSSEView()
    view.kwargs = {"session_id": session_id}
    return view


async def _subscriber_counts(redis_client, *channels) -> dict:
    return dict(await redis_client.pubsub_numsub(*channels))


async def _wait_until_subscribed(redis_client, channel):
    async with asyncio.timeout(2):
        while (await _subscriber_counts(redis_client, channel))[channel] == 0:
            await asyncio.sleep(0.01)


async def _close_while_waiting(frames):
    # A client disconnect cancels the task iterating the stream; that is how it ends.
    pending_frame = asyncio.ensure_future(anext(frames))
    await asyncio.sleep(0.05)
    pending_frame.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending_frame


async def _publish_status(redis_client, session_id, status):
    await redis_client.publish(
        f"session:update:{session_id}:status",
        json.dumps({"session_id": session_id, "status": status, "status_data": {}}),
    )


async def _publish_graph_message(redis_client, session_id, uuid):
    await redis_client.set(
        f"graph:message:{session_id}:{uuid}",
        json.dumps({"session_id": session_id, "uuid": uuid}),
    )
    await redis_client.publish(
        f"session:update:{session_id}:messages",
        json.dumps({"uuid": uuid, "session_id": session_id}),
    )


def test_run_session_view_channels_are_its_sessions_own():
    assert _run_session_view(42).get_channels() == [
        "session:update:42:status",
        "session:update:42:messages",
    ]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stream_yields_its_sessions_traffic_and_never_another_sessions(
    fake_async_redis,
):
    frames = _run_session_view(SESSION_ID).event_stream()
    first_frame = asyncio.ensure_future(anext(frames))
    await _wait_until_subscribed(fake_async_redis, f"session:update:{SESSION_ID}:messages")

    # The other session's traffic goes first: Redis keeps the order, so if it
    # reached the stream it would be what the stream yields first.
    await _publish_status(fake_async_redis, OTHER_SESSION_ID, "end")
    await _publish_graph_message(fake_async_redis, OTHER_SESSION_ID, "uuid-other")
    await _publish_status(fake_async_redis, SESSION_ID, "run")
    await _publish_graph_message(fake_async_redis, SESSION_ID, "uuid-own")

    received = [await asyncio.wait_for(first_frame, timeout=2)]
    for _ in range(3):
        received.append(await asyncio.wait_for(anext(frames), timeout=2))
    other_session_subscribers = await _subscriber_counts(
        fake_async_redis,
        f"session:update:{OTHER_SESSION_ID}:status",
        f"session:update:{OTHER_SESSION_ID}:messages",
    )
    await _close_while_waiting(frames)

    assert received == [
        "event: status\n",
        f'data: {{"session_id": {SESSION_ID}, "status": "run", "status_data": {{}}}}\n\n',
        "event: messages\n",
        f'data: {{"session_id": {SESSION_ID}, "uuid": "uuid-own"}}\n\n',
    ]
    assert set(other_session_subscribers.values()) == {0}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_closed_stream_leaves_no_subscription_behind(fake_async_redis):
    channels = [f"session:update:{SESSION_ID}:status", f"session:update:{SESSION_ID}:messages"]
    frames = _run_session_view(SESSION_ID).event_stream()
    first_frame = asyncio.ensure_future(anext(frames))
    await _wait_until_subscribed(fake_async_redis, channels[0])
    subscribed = await _subscriber_counts(fake_async_redis, *channels)

    first_frame.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_frame

    assert subscribed == {channel: 1 for channel in channels}
    assert await _subscriber_counts(fake_async_redis, *channels) == {
        channel: 0 for channel in channels
    }


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_test_mode_stream_subscribes_to_nothing(fake_async_redis):
    frames = _run_session_view(SESSION_ID).event_stream(test_mode=True)

    first_frame = await asyncio.wait_for(anext(frames), timeout=2)
    channels_during_stream = await fake_async_redis.pubsub_channels()
    remaining_frames = [frame async for frame in frames]

    assert first_frame == "data: test event #1\n\n"
    assert channels_during_stream == []
    assert remaining_frames == ["data: test event #2\n\n", "data: test event #3\n\n"]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_flow_assistant_stream_subscribes_to_nothing_and_still_streams(
    fake_async_redis,
):
    view = FlowAssistantStreamView()
    # No such conversation: the stream answers with an error event before it uses the user.
    view.kwargs = {"graph_id": 1, "conversation_id": 999_999}
    view.user = None
    frames = view.event_stream()

    event_line = await asyncio.wait_for(anext(frames), timeout=2)
    channels_during_stream = await fake_async_redis.pubsub_channels()
    data_line = await asyncio.wait_for(anext(frames), timeout=2)
    remaining_frames = [frame async for frame in frames]

    assert view.get_channels() == []
    assert channels_during_stream == []
    assert event_line == "event: error\n"
    assert json.loads(data_line.removeprefix("data: ")) == {
        "type": "error",
        "detail": "Conversation not found.",
    }
    assert remaining_frames == []
