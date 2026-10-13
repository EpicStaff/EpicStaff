import asyncio
import json
from uuid import uuid4

import fakeredis
import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from tables.models.graph_models import Graph, GraphSessionMessage
from tables.models.session_models import Session
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
    await redis_client.publish(
        f"session:update:{session_id}:messages",
        json.dumps({"session_id": session_id, "uuid": uuid}),
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


def _create_session_with_messages(org, message_count):
    graph = Graph.objects.create(name="sse-replay", org=org)
    session = Session.objects.create(graph=graph, status=Session.SessionStatus.RUN, variables={})
    messages = [
        GraphSessionMessage.objects.create(
            session=session,
            created_at=timezone.now(),
            execution_order=index,
            message_data={"message_type": "agent"},
            uuid=uuid4(),
        )
        for index in range(message_count)
    ]
    return session.id, [str(message.uuid) for message in messages]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_initial_messages_are_replayed_from_the_database_only(
    fake_async_redis, default_org
):
    session_id, stored_uuids = await sync_to_async(_create_session_with_messages)(
        default_org, 2
    )
    # A leftover of the old per-message cache must not be replayed.
    await fake_async_redis.set(
        f"graph:message:{session_id}:cached-only",
        json.dumps({"uuid": "cached-only", "message_data": {}, "timestamp": "2026-10-05"}),
    )

    initial_events = [event async for event in _run_session_view(session_id).get_initial_data()]

    replayed_uuids = [
        str(event["data"]["uuid"]) for event in initial_events if event["event"] == "messages"
    ]
    assert replayed_uuids == stored_uuids


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


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_replay_sends_every_page_of_a_long_history_in_order(fake_async_redis, default_org):
    message_count = sse_views.MESSAGE_PAGE_SIZE * 2 + 5
    session_id, stored_uuids = await sync_to_async(_create_session_with_messages)(
        default_org, message_count
    )

    initial_events = [event async for event in _run_session_view(session_id).get_initial_data()]

    replayed = [event["data"] for event in initial_events if event["event"] == "messages"]
    assert [str(message["uuid"]) for message in replayed] == stored_uuids
    assert [message["execution_order"] for message in replayed] == list(range(message_count))
    assert set(replayed[0]) >= {"id", "session_id", "uuid", "message_data", "created_at"}


def _create_message(session_id, index, **fields):
    return GraphSessionMessage.objects.create(
        session_id=session_id,
        created_at=timezone.now(),
        execution_order=index,
        message_data={"message_type": "agent", "index": index},
        uuid=uuid4(),
        **fields,
    )


async def _next_event(frames) -> tuple[str, dict]:
    event_line = await asyncio.wait_for(anext(frames), timeout=5)
    data_line = await asyncio.wait_for(anext(frames), timeout=5)
    return event_line.removeprefix("event: ").strip(), json.loads(data_line.removeprefix("data: "))


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_messages_published_during_the_replay_are_read_off_redis_and_sent_after_it(
    fake_async_redis, default_org
):
    message_count = sse_views.MESSAGE_PAGE_SIZE + 5
    session_id, stored_uuids = await sync_to_async(_create_session_with_messages)(
        default_org, message_count + 1
    )
    # A hole in the ids, for a message that commits after the replay passed its place.
    gap_message = await GraphSessionMessage.objects.aget(uuid=stored_uuids[2])
    gap_id = gap_message.id
    await gap_message.adelete()
    stored_uuids.pop(2)
    frames = _run_session_view(session_id).event_stream()
    replayed = [await _next_event(frames) for _ in range(sse_views.MESSAGE_PAGE_SIZE)]

    late_message = await sync_to_async(_create_message)(session_id, 99, id=gap_id)
    newest_message = await sync_to_async(_create_message)(session_id, 100)
    await _publish_graph_message(fake_async_redis, session_id, str(late_message.uuid))
    await _publish_graph_message(fake_async_redis, session_id, str(newest_message.uuid))
    await _publish_status(fake_async_redis, session_id, "end")
    replayed += [await _next_event(frames) for _ in range(6)]
    sent_after_replay = [await _next_event(frames) for _ in range(3)]
    await _close_while_waiting(frames)

    assert [event for event, _ in replayed] == ["messages"] * 26
    assert [str(data["uuid"]) for _, data in replayed] == [
        *stored_uuids,
        str(newest_message.uuid),
    ]
    assert sent_after_replay[0][0] == "status"
    assert sent_after_replay[0][1]["status"] == "run"
    # Read back from the database (it has an id): the payload was not kept in memory.
    assert sent_after_replay[1][0] == "messages"
    assert str(sent_after_replay[1][1]["uuid"]) == str(late_message.uuid)
    assert sent_after_replay[1][1]["id"] == gap_id
    # The newest message was replayed already, so only the status follows.
    assert sent_after_replay[2] == (
        "status",
        {"session_id": session_id, "status": "end", "status_data": {}},
    )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_held_uuid_of_another_sessions_message_is_never_read_back_into_the_stream(
    fake_async_redis, default_org
):
    session_id, stored_uuids = await sync_to_async(_create_session_with_messages)(
        default_org, sse_views.MESSAGE_PAGE_SIZE + 2
    )
    # Another run of the same flow.
    other_session = await Session.objects.acreate(
        graph_id=(await Session.objects.aget(id=session_id)).graph_id,
        status=Session.SessionStatus.RUN,
        variables={},
    )
    other_session_id = other_session.id
    other_messages = [
        await GraphSessionMessage.objects.acreate(
            session_id=other_session_id,
            created_at=timezone.now(),
            execution_order=index,
            message_data={"secret": f"other-session-{index}"},
            uuid=uuid4(),
        )
        for index in range(2)
    ]
    other_uuids = {str(message.uuid) for message in other_messages}
    # A hole in the ids, so this session's late message can only arrive by the readback.
    gap_message = await GraphSessionMessage.objects.aget(uuid=stored_uuids[2])
    gap_id = gap_message.id
    await gap_message.adelete()
    stored_uuids.pop(2)
    frames = _run_session_view(session_id).event_stream()
    replayed = [await _next_event(frames) for _ in range(sse_views.MESSAGE_PAGE_SIZE)]

    late_message = await sync_to_async(_create_message)(session_id, 99, id=gap_id)
    # Both arrive on this session's own channel, so both are held by uuid; one
    # claims this session, the other names the session that owns the row.
    for message, claimed_session_id in zip(other_messages, [session_id, other_session_id]):
        await fake_async_redis.publish(
            f"session:update:{session_id}:messages",
            json.dumps({"session_id": claimed_session_id, "uuid": str(message.uuid)}),
        )
    await _publish_graph_message(fake_async_redis, session_id, str(late_message.uuid))
    await _publish_status(fake_async_redis, session_id, "end")
    replayed.append(await _next_event(frames))
    sent_after_replay = [await _next_event(frames) for _ in range(3)]
    await _close_while_waiting(frames)

    assert [str(data["uuid"]) for _, data in replayed] == stored_uuids
    assert sent_after_replay[0][0] == "status"
    assert sent_after_replay[0][1]["status"] == "run"
    assert sent_after_replay[1][0] == "messages"
    assert str(sent_after_replay[1][1]["uuid"]) == str(late_message.uuid)
    assert sent_after_replay[1][1]["id"] == gap_id
    assert sent_after_replay[2] == (
        "status",
        {"session_id": session_id, "status": "end", "status_data": {}},
    )
    streamed = json.dumps([data for _, data in replayed + sent_after_replay], default=str)
    assert not any(other_uuid in streamed for other_uuid in other_uuids)
    assert "other-session" not in streamed
