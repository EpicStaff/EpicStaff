import asyncio
import json
import re
import time
from contextlib import aclosing
from datetime import datetime
from uuid import UUID

import pytest
from application.orchestrators.streams import STREAMS_PER_CONVERSATION, STREAMS_PER_IP, StreamOrchestrator
from common.utils import new_id, utcnow
from domain.enums import Stream
from domain.errors import RateLimitedError
from domain.models import ConversationEvent
from infrastructure.callback_verifier import SESSION_ID_HEADER, SIGNATURE_HEADER, TIMESTAMP_HEADER, sign
from infrastructure.database.models import CallbackReceiptRow
from sqlalchemy import select, text
from tests.factories import make_binding
from tests.infrastructure.test_django_client import CHAT_FLOW
from tests.integration.test_operator_api import ALL, BASE, h

ORIGIN = "https://example.com"


def parse_sse(text: str) -> list[dict]:
    """Minimal SSE parser: one dict per event with id/event/data/comment."""
    events, current = [], {}
    for line in text.splitlines():
        if not line:
            if current:
                events.append(current)
            current = {}
        elif line.startswith(":"):
            current["comment"] = line[1:].strip()
        else:
            field, _, value = line.partition(":")
            current[field] = value.strip()
    if current:
        events.append(current)
    return events


async def read_stream(client, url, headers, seconds: float) -> list[dict]:
    """Drive the ASGI app directly: AsyncTestClient and httpx.ASGITransport both buffer the whole body."""
    path, _, query = url.partition("?")
    disconnect = asyncio.Event()
    started, chunks = {}, []

    async def receive():
        if not started.get("request_sent"):
            started["request_sent"] = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            started.update(status=message["status"], headers={k.decode(): v.decode() for k, v in message["headers"]})
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": query.encode(), "root_path": "",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": ("127.0.0.1", 1234), "server": ("testserver", 80), "state": {},
    }
    app = asyncio.create_task(client.app(scope, receive, send))
    done, _ = await asyncio.wait({app}, timeout=seconds)
    if not done:
        disconnect.set()
        try:
            await asyncio.wait_for(app, timeout=2)
        except TimeoutError:
            pass
    assert started["status"] == 200, b"".join(chunks)
    assert started["headers"]["content-type"].startswith("text/event-stream")
    return parse_sse(b"".join(chunks).decode())


@pytest.fixture
async def conversation(client, uow_factory, django):
    django.graphs[5] = CHAT_FLOW
    binding = make_binding(org_id=1, graph_id=5)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.commit()
    created = (await client.post("/chat/public/v1/conversations", json={"public_key": binding.public_key}, headers={"Origin": ORIGIN})).json()
    return created["conversation_id"], {"Authorization": f"Bearer {created['visitor_token']}", "Origin": ORIGIN}, binding.public_key


async def test_ticket_is_required_single_use_and_bound_to_the_conversation(client, conversation):
    conversation_id, headers, public_key = conversation
    ticket = await client.post(f"/chat/public/v1/conversations/{conversation_id}/stream-ticket", headers=headers)
    assert ticket.status_code == 201 and ticket.json()["expires_in"] == 60
    assert (await client.get(f"/chat/public/v1/conversations/{conversation_id}/stream")).status_code == 401
    assert (await client.get(f"/chat/public/v1/conversations/{conversation_id}/stream?ticket=nope")).status_code == 401
    other = (await client.post("/chat/public/v1/conversations", json={"public_key": public_key}, headers={"Origin": ORIGIN})).json()
    wrong = await client.get(f"/chat/public/v1/conversations/{other['conversation_id']}/stream?ticket={ticket.json()['ticket']}")
    assert wrong.status_code == 401
    assert (await client.get(f"/chat/public/v1/conversations/{conversation_id}/stream?ticket={ticket.json()['ticket']}")).status_code == 401  # consumed by the wrong attempt


async def test_replay_then_live(client, conversation):
    conversation_id, headers, _ = conversation
    await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json={"content": "first"}, headers=headers)
    ticket = (await client.post(f"/chat/public/v1/conversations/{conversation_id}/stream-ticket", headers=headers)).json()["ticket"]

    async def send_later():
        await asyncio.sleep(0.3)
        async with client.app.state.session_factory() as session:  # the run Django started as session 100
            receipt = (await session.execute(select(CallbackReceiptRow).where(CallbackReceiptRow.session_id == 100))).scalar_one()
        payload = {"session_id": 100, "graph_id": 5, "status": "end", "end_node_result": {"reply": "pong"}, "token_usage": {}, "finished_at": "x"}
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        timestamp = str(int(time.time()))
        await client.post(f"/chat/internal/v1/session-callbacks/{receipt.run_id}", content=body, headers={SESSION_ID_HEADER: "100", TIMESTAMP_HEADER: timestamp, SIGNATURE_HEADER: sign(receipt.secret, timestamp, body), "Content-Type": "application/json"})

    sender = asyncio.create_task(send_later())
    events = await read_stream(client, f"/chat/public/v1/conversations/{conversation_id}/stream?ticket={ticket}", {"Last-Event-ID": "0"}, seconds=1.5)
    await sender
    rows = [e for e in events if e.get("event") not in (None, "ready")]
    types = [e["event"] for e in rows]
    assert types[:2] == ["message.created", "run.started"]           # replayed from the table
    assert "message.created" in types[2:] and types[-1] == "run.finished"  # pushed live
    assert events.index(next(e for e in events if e.get("event") == "ready")) == 2  # right after the replay
    ids = [int(e["id"]) for e in rows]
    assert len(ids) == len(set(ids))  # live rows may arrive out of seq order, never twice


async def test_last_event_id_skips_known_rows_and_old_cursor_resets(client, conversation, uow_factory):
    conversation_id, headers, _ = conversation
    await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json={"content": "first"}, headers=headers)
    ticket = (await client.post(f"/chat/public/v1/conversations/{conversation_id}/stream-ticket", headers=headers)).json()["ticket"]
    all_events = await read_stream(client, f"/chat/public/v1/conversations/{conversation_id}/stream?ticket={ticket}", {"Last-Event-ID": "0"}, seconds=0.5)
    first_id = int(next(e["id"] for e in all_events if "id" in e))
    ticket = (await client.post(f"/chat/public/v1/conversations/{conversation_id}/stream-ticket", headers=headers)).json()["ticket"]
    later = await read_stream(client, f"/chat/public/v1/conversations/{conversation_id}/stream?ticket={ticket}", {"Last-Event-ID": str(first_id)}, seconds=1.5)  # past an idle re-read
    assert all(int(e["id"]) > first_id for e in later if "id" in e) and len([e for e in later if "id" in e]) == len([e for e in all_events if "id" in e]) - 1

    async with uow_factory() as uow:  # pretend retention removed the first rows: the cursor is now older than anything stored
        await uow._session.execute(text("DELETE FROM conversation_event WHERE seq <= :s"), {"s": first_id})
        await uow.commit()
    ticket = (await client.post(f"/chat/public/v1/conversations/{conversation_id}/stream-ticket", headers=headers)).json()["ticket"]
    reset = await read_stream(client, f"/chat/public/v1/conversations/{conversation_id}/stream?ticket={ticket}", {"Last-Event-ID": str(first_id)}, seconds=0.5)
    assert reset[0].get("event") == "reset"
    assert [int(e["id"]) for e in reset[1:] if "id" in e and e["event"] != "ready"] == [int(e["id"]) for e in later if "id" in e and e["event"] != "ready"]  # then everything still stored
    assert int(next(e["id"] for e in reset if e.get("event") == "ready")) >= max(int(e["id"]) for e in later if "id" in e)  # ready names this conversation's head


async def test_a_cursor_with_no_surviving_rows_in_scope_opens_at_zero(client, conversation, uow_factory):
    conversation_id, headers, _ = conversation
    await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json={"content": "first"}, headers=headers)
    async with uow_factory() as uow:  # retention removed this conversation's rows; the inbox rows survive but are out of scope
        await uow._session.execute(text("DELETE FROM conversation_event WHERE stream = 'conversation'"))
        await uow.commit()
        scope = {"conversation_id": UUID(conversation_id)}
        head, oldest = await uow.events.max_seq(Stream.CONVERSATION, **scope), await uow.events.min_seq(Stream.CONVERSATION, **scope)
        assert await uow.events.max_seq(Stream.INBOX, org_id=1) >= 1
    assert head == 0 and oldest == 0
    ticket = (await client.post(f"/chat/public/v1/conversations/{conversation_id}/stream-ticket", headers=headers)).json()["ticket"]
    events = await read_stream(client, f"/chat/public/v1/conversations/{conversation_id}/stream?ticket={ticket}", {"Last-Event-ID": "0"}, seconds=0.5)
    # The cursor never names another conversation's or org's seq, so it reveals nothing about their volume.
    assert [e["event"] for e in events if "event" in e] == ["ready"]
    assert int(next(e["id"] for e in events if e.get("event") == "ready")) == 0


async def test_inbox_stream_is_org_scoped(client, conversation, django):
    django.users["admin"] = {"active": True, "user_id": 1, "email": "a@x", "scopes": [], "org_ids": [1, 2], "is_superadmin": False}
    django.permissions[("admin", 1)] = {"chats": ALL}
    django.permissions[("admin", 2)] = {"chats": ALL}
    conversation_id, headers, _ = conversation
    await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json={"content": "first"}, headers=headers)
    ticket_1 = (await client.post(f"{BASE}/inbox/stream-ticket", headers=h("admin", 1))).json()["ticket"]
    ticket_2 = (await client.post(f"{BASE}/inbox/stream-ticket", headers=h("admin", 2))).json()["ticket"]
    org_1 = await read_stream(client, f"{BASE}/inbox/stream?ticket={ticket_1}", {"Last-Event-ID": "0"}, seconds=0.5)
    org_2 = await read_stream(client, f"{BASE}/inbox/stream?ticket={ticket_2}", {"Last-Event-ID": "0"}, seconds=0.5)
    assert [e["event"] for e in org_1 if "event" in e] == ["message.created", "conversation.updated", "conversation.updated", "ready"]
    assert [e["event"] for e in org_2 if "event" in e] == ["ready"]
    assert (await client.get(f"{BASE}/inbox/stream?ticket={ticket_1}")).status_code == 401  # single use
    assert (await client.post(f"{BASE}/inbox/stream-ticket", headers=h("admin", 3))).status_code == 404


async def test_pings_keep_the_stream_alive(client, conversation, settings):
    conversation_id, headers, _ = conversation
    ticket = (await client.post(f"/chat/public/v1/conversations/{conversation_id}/stream-ticket", headers=headers)).json()["ticket"]
    events = await read_stream(client, f"/chat/public/v1/conversations/{conversation_id}/stream?ticket={ticket}", {}, seconds=settings.CHAT_STREAM_PING_INTERVAL + 0.5)
    assert any(e.get("comment") == "ping" for e in events)


def conversation_event(conversation_id: str, type: str) -> ConversationEvent:
    return ConversationEvent(id=new_id(), stream=Stream.CONVERSATION, conversation_id=UUID(conversation_id), org_id=1, type=type, payload={}, created_at=utcnow())


async def collect_events(client, uow_factory, conversation_id: str, prefix: str, expected: int, last_event_id: int | None = None) -> list[str]:
    streams = StreamOrchestrator(uow_factory, fanout=client.app.state.fanout, limiter=client.app.state.limiter, ping_seconds=1, max_seconds=5)
    received = []
    async with aclosing(await streams.conversation_stream(UUID(conversation_id), last_event_id, "127.0.0.1")) as messages:
        async for message in messages:
            if message.event and message.event.startswith(prefix):
                received.append(message.event)
            if len(received) == expected:
                return received
    return received


async def test_a_late_committed_lower_seq_is_not_dropped(client, conversation, uow_factory):
    """seq is assigned at insert, not commit: a row committed after a higher seq was already sent must still arrive, once.

    Order across reads is not part of the contract (rows go out as they become visible), so the test
    drives the one order that matters with handshakes: b is sent before a is committed.
    """
    conversation_id, _, _ = conversation
    channel = f"chat:conversation:{conversation_id}"
    # Short pings so the closing exactly-once check (two more idle re-reads) costs well under a second.
    streams = StreamOrchestrator(uow_factory, fanout=client.app.state.fanout, limiter=client.app.state.limiter, ping_seconds=0.2, max_seconds=5)
    received: asyncio.Queue[str] = asyncio.Queue()

    async def follow():
        async with aclosing(await streams.conversation_stream(UUID(conversation_id), None, "127.0.0.1")) as messages:
            async for message in messages:
                received.put_nowait(message.event or message.comment)

    async def next_event() -> str:
        # Idle-tick pings can fall anywhere; only the events are ordered by this test.
        while (item := await asyncio.wait_for(received.get(), timeout=3)) == "ping":
            pass
        return item

    follower = asyncio.create_task(follow())
    try:
        assert await next_event() == "ready"  # subscribed and caught up: nothing to replay
        async with uow_factory() as slow, uow_factory() as fast:
            seq_a = await slow.events.add(conversation_event(conversation_id, "late.a"))  # lower seq, committed last
            seq_b = await fast.events.add(conversation_event(conversation_id, "late.b"))
            await fast.commit()
            await client.app.state.fanout.publish(channel, {"seq": seq_b, "type": "late.b", "payload": {}})
            # b is out before a is visible: the stream's high-water mark is now past seq_a.
            assert await next_event() == "late.b"
            await slow.commit()
            await client.app.state.fanout.publish(channel, {"seq": seq_a, "type": "late.a", "payload": {}})
        assert seq_a < seq_b
        assert await next_event() == "late.a"
        # The second ping after a comes from an idle re-read that started after a was sent:
        # every read covering both rows has run and resent neither.
        after_a = []
        while after_a.count("ping") < 2:
            after_a.append(await asyncio.wait_for(received.get(), timeout=3))
        assert set(after_a) == {"ping"}
    finally:
        follower.cancel()
        await asyncio.gather(follower, return_exceptions=True)


async def test_a_row_without_a_publish_arrives_on_the_next_idle_tick(client, conversation, uow_factory):
    conversation_id, _, _ = conversation
    collector = asyncio.create_task(collect_events(client, uow_factory, conversation_id, "quiet.", 1))
    await asyncio.sleep(0.2)
    async with uow_factory() as uow:
        await uow.events.add(conversation_event(conversation_id, "quiet.row"))
        await uow.commit()
    assert await asyncio.wait_for(collector, timeout=1.5) == ["quiet.row"]


async def test_no_cursor_starts_from_now(client, conversation, uow_factory):
    conversation_id, _, _ = conversation
    async with uow_factory() as uow:
        await uow.events.add(conversation_event(conversation_id, "now.old"))
        await uow.commit()
    collector = asyncio.create_task(collect_events(client, uow_factory, conversation_id, "now.", 1))
    await asyncio.sleep(0.2)
    async with uow_factory() as uow:
        seq = await uow.events.add(conversation_event(conversation_id, "now.new"))
        await uow.commit()
    await client.app.state.fanout.publish(f"chat:conversation:{conversation_id}", {"seq": seq, "type": "now.new", "payload": {}})
    assert await asyncio.wait_for(collector, timeout=1.5) == ["now.new"]


async def test_disconnect_releases_the_subscription(client, conversation, redis_client):
    conversation_id, headers, _ = conversation
    channel = f"chat:conversation:{conversation_id}"
    ticket = (await client.post(f"/chat/public/v1/conversations/{conversation_id}/stream-ticket", headers=headers)).json()["ticket"]
    observed = {}

    async def watch():
        await asyncio.sleep(0.15)
        observed["open"] = await redis_client.pubsub_numsub(channel)

    watcher = asyncio.create_task(watch())
    await read_stream(client, f"/chat/public/v1/conversations/{conversation_id}/stream?ticket={ticket}", {}, seconds=0.3)
    await watcher
    assert observed["open"] == [(channel.encode(), 1)]
    assert await redis_client.pubsub_numsub(channel) == [(channel.encode(), 0)]


async def test_a_stream_without_a_cursor_opens_with_ready(client, conversation, uow_factory):
    """EventSource reconnects with the last id it saw; `ready` gives one even to a quiet stream."""
    conversation_id, headers, _ = conversation
    await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json={"content": "first"}, headers=headers)
    async with uow_factory() as uow:
        high_seq = await uow.events.max_seq(Stream.CONVERSATION, conversation_id=UUID(conversation_id))
    ticket = (await client.post(f"/chat/public/v1/conversations/{conversation_id}/stream-ticket", headers=headers)).json()["ticket"]
    events = await read_stream(client, f"/chat/public/v1/conversations/{conversation_id}/stream?ticket={ticket}", {}, seconds=0.3)
    assert events[0]["event"] == "ready" and int(events[0]["id"]) == high_seq and events[0]["data"] == "{}"


async def test_concurrent_streams_per_conversation_are_capped(client, conversation, redis_client):
    conversation_id, headers, _ = conversation
    url = f"/chat/public/v1/conversations/{conversation_id}/stream?ticket="

    async def ticket():
        return (await client.post(f"/chat/public/v1/conversations/{conversation_id}/stream-ticket", headers=headers)).json()["ticket"]

    tickets = [await ticket() for _ in range(STREAMS_PER_CONVERSATION)]
    open_streams = [asyncio.create_task(read_stream(client, url + t, {}, seconds=0.6)) for t in tickets]
    await asyncio.sleep(0.2)
    refused = await client.get(url + await ticket())
    assert refused.status_code == 429 and refused.json()["code"] == "rate_limited"
    await asyncio.gather(*open_streams)
    assert await redis_client.zcard(f"chat:streams:conv:{conversation_id}") == 0
    assert await redis_client.zcard("chat:streams:ip:127.0.0.1") == 0


async def test_a_stream_whose_client_stops_reading_keeps_its_slot(client, conversation, uow_factory, redis_client):
    """A ping of 0.2 s gives a 1 s lease. The consumer reads `ready` and then nothing, parking the generator on
    `yield`; the slot must stay counted well past the lease, or a non-reading client could open streams past the cap."""
    conversation_id, _, _ = conversation
    key = f"chat:streams:conv:{conversation_id}"
    streams = StreamOrchestrator(uow_factory, fanout=client.app.state.fanout, limiter=client.app.state.limiter, ping_seconds=0.2, max_seconds=10)
    async with aclosing(await streams.conversation_stream(UUID(conversation_id), None, "127.0.0.1")) as messages:
        assert (await anext(messages)).event == "ready"
        await asyncio.sleep(2.5)
        assert await redis_client.zcount(key, f"({time.time()}", "+inf") == 1
    assert await redis_client.zcard(key) == 0
    assert not [task for task in asyncio.all_tasks() if "_keep_renewed" in repr(task.get_coro())]


async def test_a_refused_second_slot_gives_back_the_first(client, conversation, uow_factory, redis_client):
    conversation_id, _, _ = conversation
    limiter = client.app.state.limiter
    for n in range(STREAMS_PER_IP):
        assert await limiter.acquire_slot("chat:streams:ip:127.0.0.1", STREAMS_PER_IP, f"other-{n}", 60)
    streams = StreamOrchestrator(uow_factory, fanout=client.app.state.fanout, limiter=limiter, ping_seconds=1, max_seconds=5)
    with pytest.raises(RateLimitedError):
        await streams.conversation_stream(UUID(conversation_id), None, "127.0.0.1")
    assert await redis_client.zcard(f"chat:streams:conv:{conversation_id}") == 0
    assert await redis_client.zcard("chat:streams:ip:127.0.0.1") == STREAMS_PER_IP


async def test_ipv6_stream_slots_are_counted_per_slash_64(client, conversation, uow_factory):
    conversation_id, _, _ = conversation
    limiter = client.app.state.limiter
    for n in range(STREAMS_PER_IP):
        assert await limiter.acquire_slot("chat:streams:ip:2001:db8:1:2::/64", STREAMS_PER_IP, f"other-{n}", 60)
    streams = StreamOrchestrator(uow_factory, fanout=client.app.state.fanout, limiter=limiter, ping_seconds=1, max_seconds=5)
    with pytest.raises(RateLimitedError):
        await streams.conversation_stream(UUID(conversation_id), None, "2001:db8:1:2::abcd")
    async with aclosing(await streams.conversation_stream(UUID(conversation_id), None, "2001:db8:1:3::1")) as messages:
        assert (await anext(messages)).event == "ready"


async def test_stream_connect_rechecks_that_the_binding_is_active(client, conversation, uow_factory):
    conversation_id, headers, public_key = conversation
    ticket = (await client.post(f"/chat/public/v1/conversations/{conversation_id}/stream-ticket", headers=headers)).json()["ticket"]
    async with uow_factory() as uow:
        binding = await uow.bindings.get_by_public_key(public_key)
        binding.is_active = False
        await uow.bindings.update(binding)
        await uow.commit()
    refused = await client.get(f"/chat/public/v1/conversations/{conversation_id}/stream?ticket={ticket}")
    assert (refused.status_code, refused.json()["code"]) == (410, "binding_inactive")



async def test_operator_names_reach_the_inbox_but_never_the_visitor(client, conversation, django, uow_factory):
    """Visitors see an operator's alias on the desk, else the desk's operator_display_name; who
    the operator is (real name, email, id) stays with operators, and so does an alias the same
    operator uses on another desk."""
    django.users["agent"] = {"active": True, "user_id": 2, "email": "bea@example.com", "display_name": "Bea Agent", "scopes": [], "org_ids": [1], "is_superadmin": False}
    django.users["admin"] = {"active": True, "user_id": 1, "email": "ada@example.com", "display_name": "Ada Admin", "scopes": [], "org_ids": [1], "is_superadmin": False}
    for user in ("agent", "admin"):
        django.permissions[(user, 1)] = {"chats": ALL}
    conversation_id, headers, _ = conversation
    async with uow_factory() as uow:
        desk_id = (await uow.conversations.get(UUID(conversation_id))).binding_id
    other_desk = make_binding(org_id=1, graph_id=5)
    async with uow_factory() as uow:
        await uow.bindings.add(other_desk)
        await uow.commit()
    assert (await client.put(f"{BASE}/bindings/{desk_id}/my-alias", json={"alias": "Mike"}, headers=h("agent"))).status_code == 200
    assert (await client.put(f"{BASE}/bindings/{other_desk.id}/my-alias", json={"alias": "Zed"}, headers=h("agent"))).status_code == 200

    await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json={"content": "help"}, headers=headers)
    assert (await client.post(f"{BASE}/conversations/{conversation_id}/claim", json={}, headers=h("agent"))).status_code == 200
    assert (await client.post(f"{BASE}/conversations/{conversation_id}/messages", json={"content": "Hello from the team"}, headers=h("agent"))).status_code == 201
    await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json={"content": "thanks"}, headers=headers)
    # An operator with no alias on this desk replies under the desk's operator name.
    assert (await client.post(f"{BASE}/conversations/{conversation_id}/claim", json={"force": True}, headers=h("admin"))).status_code == 200
    assert (await client.post(f"{BASE}/conversations/{conversation_id}/messages", json={"content": "Taking over"}, headers=h("admin"))).status_code == 201

    ticket = (await client.post(f"{BASE}/inbox/stream-ticket", headers=h("agent"))).json()["ticket"]
    inbox = await read_stream(client, f"{BASE}/inbox/stream?ticket={ticket}", {"Last-Event-ID": "0"}, seconds=0.5)
    assert "Bea Agent" in json.dumps(inbox) and "Ada Admin" in json.dumps(inbox)  # the names are in the system, for operators

    ticket = (await client.post(f"/chat/public/v1/conversations/{conversation_id}/stream-ticket", headers=headers)).json()["ticket"]
    visitor_stream = await read_stream(client, f"/chat/public/v1/conversations/{conversation_id}/stream?ticket={ticket}", {"Last-Event-ID": "0"}, seconds=0.5)
    state = await client.get(f"/chat/public/v1/conversations/{conversation_id}", headers=headers)
    messages = await client.get(f"/chat/public/v1/conversations/{conversation_id}/messages", headers=headers)
    created = [json.loads(e["data"]) for e in visitor_stream if e.get("event") == "message.created"]
    assert [(m["role"], m["visible_name"]) for m in created] == [("user", None), ("operator", "Mike"), ("user", None), ("operator", "Support")]
    assert [m["visible_name"] for m in messages.json()] == [None, "Mike", None, "Support"]
    for text, expected_key in ((json.dumps(visitor_stream), "role"), (state.text, "mode"), (messages.text, "role")):
        keys = set(re.findall(r'\\?"(\w+)\\?":', text))  # also the keys inside each event's JSON data
        assert expected_key in keys and not {"author_user_id", "author_name", "assigned_operator_id", "assigned_operator_name", "visitor_number"} & keys
        for private in ("Bea Agent", "bea@example.com", "Ada Admin", "ada@example.com", "Zed"):
            assert private not in text, private
    assert state.json()["operator_display_name"] == "Support"


async def test_a_close_tells_the_visitor_why_and_when_but_never_who_and_reaches_only_the_orgs_inbox(client, conversation, django):
    django.users["agent"] = {"active": True, "user_id": 2, "email": "bea@example.com", "display_name": "Bea Agent", "scopes": [], "org_ids": [1], "is_superadmin": False}
    django.users["outsider"] = {"active": True, "user_id": 9, "email": "o@example.com", "scopes": [], "org_ids": [2], "is_superadmin": False}
    django.permissions[("agent", 1)] = {"chats": ALL}
    django.permissions[("outsider", 2)] = {"chats": ALL}
    conversation_id, headers, _ = conversation
    await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json={"content": "help"}, headers=headers)
    assert (await client.post(f"{BASE}/conversations/{conversation_id}/claim", json={}, headers=h("agent"))).status_code == 200
    closed = (await client.post(f"{BASE}/conversations/{conversation_id}/close", json={}, headers=h("agent"))).json()

    ticket = (await client.post(f"/chat/public/v1/conversations/{conversation_id}/stream-ticket", headers=headers)).json()["ticket"]
    visitor = await read_stream(client, f"/chat/public/v1/conversations/{conversation_id}/stream?ticket={ticket}", {"Last-Event-ID": "0"}, seconds=0.5)
    (closed_event,) = [json.loads(e["data"]) for e in visitor if e.get("event") == "conversation.closed"]
    assert set(closed_event) == {"close_reason", "closed_at"} and closed_event["close_reason"] == "resolved"
    assert datetime.fromisoformat(closed_event["closed_at"]) == datetime.fromisoformat(closed["closed_at"])
    keys = set(re.findall(r'\\?"(\w+)\\?":', json.dumps(visitor)))
    assert not {"closed_by_user_id", "closed_by_name", "assigned_operator_id", "author_user_id"} & keys
    assert "Bea Agent" not in json.dumps(visitor) and "bea@example.com" not in json.dumps(visitor)

    ticket = (await client.post(f"{BASE}/inbox/stream-ticket", headers=h("agent"))).json()["ticket"]
    inbox = await read_stream(client, f"{BASE}/inbox/stream?ticket={ticket}", {"Last-Event-ID": "0"}, seconds=0.5)
    types = [e["event"] for e in inbox if "event" in e]
    assert types[-3:] == ["conversation.closed", "conversation.updated", "ready"]
    assert json.loads(inbox[-2]["data"])["closed_by_name"] == "Bea Agent"
    assert json.loads(next(e["data"] for e in inbox if e.get("event") == "conversation.closed"))["closed_by_user_id"] == 2
    ticket = (await client.post(f"{BASE}/inbox/stream-ticket", headers=h("outsider", 2))).json()["ticket"]
    other_org = await read_stream(client, f"{BASE}/inbox/stream?ticket={ticket}", {"Last-Event-ID": "0"}, seconds=0.5)
    assert [e["event"] for e in other_org if "event" in e] == ["ready"]
