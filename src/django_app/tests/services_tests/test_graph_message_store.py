import json
import threading
from uuid import uuid4

import fakeredis
import pytest
from django.db import OperationalError, connection, transaction
from django.utils import timezone

from tables.models.graph_models import Graph, GraphSessionMessage
from tables.models.session_models import Session
from tables.services import redis_pubsub
from tables.services.graph_message_store import GraphMessageStore

pytestmark = pytest.mark.django_db


@pytest.fixture
def redis_client():
    client = fakeredis.FakeRedis(decode_responses=True)
    yield client
    client.close()


@pytest.fixture
def store(redis_client):
    yield GraphMessageStore(redis_client)


@pytest.fixture
def graph(default_org):
    yield Graph.objects.create(name="graph-message-store", org=default_org)


@pytest.fixture
def child_graph(default_org):
    yield Graph.objects.create(name="graph-message-store-child", org=default_org)


def _session(graph, status=Session.SessionStatus.RUN):
    return Session.objects.create(graph=graph, status=status, variables={})


def _payload(session_id, message_type="agent", execution_order=1, uuid=None, **message_data):
    return json.dumps(
        {
            "session_id": session_id,
            "name": "node",
            "execution_order": execution_order,
            "timestamp": "2026-10-05T10:00:00+00:00",
            "message_data": {"message_type": message_type, **message_data},
            "uuid": uuid or str(uuid4()),
        }
    )


def _usage(total_tokens, total_cost_usd=0.0):
    return {
        "token_usage": {
            "total_tokens": total_tokens,
            "prompt_tokens": total_tokens - 1,
            "completion_tokens": 1,
            "successful_requests": 1,
            "cached_prompt_tokens": 0,
            "total_cost_usd": total_cost_usd,
        }
    }


def _uuid_of(payload):
    return json.loads(payload)["uuid"]


def _stored_uuids(session):
    return [
        str(stored_uuid)
        for stored_uuid in GraphSessionMessage.objects.filter(session=session)
        .order_by("id")
        .values_list("uuid", flat=True)
    ]


def _published(subscriber) -> list[dict]:
    # Subscribe acknowledgements are read too: with ignore_subscribe_messages,
    # get_message() returns None for them and the loop would stop early.
    messages = []
    while (message := subscriber.get_message(timeout=0.05)) is not None:
        if message["type"] == "message":
            messages.append(message)
    return messages


def _subgraph_messages(root_session, child_graph, execution_id, inner_message_count=1):
    tagged = [
        _payload(
            root_session.id,
            "agent",
            execution_order=2 + index,
            subgraph_execution_ids=[execution_id],
            **_usage(10),
        )
        for index in range(inner_message_count)
    ]
    return [
        _payload(
            root_session.id,
            "subgraph_start",
            subgraph_execution_id=execution_id,
            subgraph_id=child_graph.id,
            input={"question": "?"},
            subgraph_execution_ids=[],
        ),
        *tagged,
        _payload(
            root_session.id,
            "subgraph_finish",
            subgraph_execution_id=execution_id,
            output={"answer": "!"},
        ),
    ]


def test_batch_is_stored_in_stream_order_with_its_fields(graph, store):
    session = _session(graph)
    other_session = _session(graph)
    subgraph_execution_id = str(uuid4())
    payloads = [
        _payload(session.id, "start", execution_order=3),
        _payload(other_session.id, "start", execution_order=1),
        _payload(
            session.id,
            "finish",
            execution_order=2,
            subgraph_execution_ids=[subgraph_execution_id, str(uuid4())],
        ),
    ]

    store.persist_batch(payloads)

    stored = list(GraphSessionMessage.objects.order_by("id"))
    assert [str(message.uuid) for message in stored] == [_uuid_of(p) for p in payloads]
    assert [message.session_id for message in stored] == [
        session.id,
        other_session.id,
        session.id,
    ]
    assert [message.execution_order for message in stored] == [3, 1, 2]
    assert [message.message_data["message_type"] for message in stored] == [
        "start",
        "start",
        "finish",
    ]
    assert [
        str(message.parent_subgraph_execution_id)
        if message.parent_subgraph_execution_id
        else None
        for message in stored
    ] == [None, None, subgraph_execution_id]
    assert stored[0].created_at.isoformat() == "2026-10-05T10:00:00+00:00"


def test_each_message_is_published_unchanged_only_on_its_own_sessions_channel(
    graph, store, redis_client
):
    session = _session(graph)
    other_session = _session(graph)
    subscriber = redis_client.pubsub()
    subscriber.subscribe(
        f"session:update:{session.id}:messages",
        f"session:update:{other_session.id}:messages",
    )
    # Compact separators and a non-ASCII character: re-serialising would change the string.
    own_payload = json.dumps(
        json.loads(_payload(session.id, text="Agent ✓")), separators=(",", ":"), ensure_ascii=False
    )
    other_payload = _payload(other_session.id)

    store.persist_batch([other_payload, own_payload])

    published = _published(subscriber)
    subscriber.close()
    assert [(message["channel"], message["data"]) for message in published] == [
        (f"session:update:{other_session.id}:messages", other_payload),
        (f"session:update:{session.id}:messages", own_payload),
    ]


def test_message_repeated_within_a_batch_is_stored_published_and_counted_once(
    graph, store, redis_client
):
    session = _session(graph)
    subscriber = redis_client.pubsub()
    subscriber.subscribe(f"session:update:{session.id}:messages")
    repeated_payload = _payload(session.id, **_usage(5))
    # crew retries a failed XADD, so the same message can be in a batch twice.
    payloads = [repeated_payload, _payload(session.id), repeated_payload]

    store.persist_batch(payloads)

    published = _published(subscriber)
    subscriber.close()
    assert _stored_uuids(session) == [_uuid_of(payloads[0]), _uuid_of(payloads[1])]
    assert [message["data"] for message in published] == payloads[:2]
    assert redis_client.hget(f"session:{session.id}:token_usage", "total_tokens") == "5"


def test_redelivered_batch_is_stored_counted_and_finished_once(
    graph, child_graph, store, redis_client
):
    session = _session(graph)
    payloads = [
        _payload(session.id, **_usage(100, 0.5)),
        *_subgraph_messages(session, child_graph, str(uuid4())),
        _payload(session.id, "graph_end"),
    ]

    store.persist_batch(payloads)
    store.persist_batch(payloads)

    assert _stored_uuids(session) == [_uuid_of(payload) for payload in payloads]
    assert Session.objects.filter(parent_session=session).count() == 1
    child_session = Session.objects.get(parent_session=session)
    assert GraphSessionMessage.objects.filter(session=child_session).count() == 1
    session.refresh_from_db()
    assert session.token_usage["total_tokens"] == 110
    assert session.token_usage["total_cost_usd"] == pytest.approx(0.5)
    assert redis_client.hget(f"session:{session.id}:token_usage", "total_tokens") == "110"


def test_messages_of_a_deleted_session_are_skipped_and_the_others_stored(
    graph, store, redis_client
):
    session = _session(graph)
    deleted_session = _session(graph)
    deleted_session_id = deleted_session.id
    deleted_session.delete()
    subscriber = redis_client.pubsub()
    subscriber.subscribe(f"session:update:{deleted_session_id}:messages")
    payloads = [
        _payload(deleted_session_id, **_usage(7)),
        _payload(session.id),
    ]

    store.persist_batch(payloads)

    published = _published(subscriber)
    subscriber.close()
    assert _stored_uuids(session) == [_uuid_of(payloads[1])]
    assert not GraphSessionMessage.objects.filter(session_id=deleted_session_id).exists()
    assert published == []
    assert not redis_client.exists(f"session:{deleted_session_id}:token_usage")


def test_message_the_database_rejects_is_dropped_alone_and_its_sessions_graph_end_lands(
    graph, store, redis_client
):
    session = _session(graph)
    session_with_bad_row = _session(graph)
    subscriber = redis_client.pubsub()
    subscriber.subscribe(f"session:update:{session_with_bad_row.id}:messages")
    payloads = [
        _payload(session.id, execution_order=1),
        _payload(session_with_bad_row.id, execution_order=1, **_usage(9)),
        # PostgreSQL jsonb cannot hold a NUL character: the INSERT is rejected.
        _payload(session_with_bad_row.id, execution_order=2, text="bad \u0000 output", **_usage(4)),
        _payload(session.id, execution_order=2),
        _payload(session_with_bad_row.id, "graph_end", execution_order=3),
    ]

    store.persist_batch(payloads)

    published = _published(subscriber)
    subscriber.close()
    session_with_bad_row.refresh_from_db()
    assert _stored_uuids(session) == [_uuid_of(payloads[0]), _uuid_of(payloads[3])]
    assert _stored_uuids(session_with_bad_row) == [_uuid_of(payloads[1]), _uuid_of(payloads[4])]
    assert [message["data"] for message in published] == [payloads[1], payloads[4]]
    assert session_with_bad_row.token_usage["total_tokens"] == 9


def test_session_whose_rows_all_fail_does_not_lose_other_sessions(graph, store, redis_client):
    session = _session(graph)
    rejected_session = _session(graph)
    payloads = [
        _payload(session.id, execution_order=1),
        # Out of the integer column's range: Postgres rejects the INSERT.
        _payload(rejected_session.id, execution_order=2**40, **_usage(9)),
        _payload(session.id, execution_order=2),
    ]

    store.persist_batch(payloads)

    assert _stored_uuids(session) == [_uuid_of(payloads[0]), _uuid_of(payloads[2])]
    assert not GraphSessionMessage.objects.filter(session=rejected_session).exists()
    assert not redis_client.exists(f"session:{rejected_session.id}:token_usage")


@pytest.mark.parametrize(
    "malformed_payload",
    [
        "not json",
        json.dumps({"session_id": 1, "uuid": str(uuid4())}),
        json.dumps(
            {
                "session_id": 1,
                "name": "",
                "execution_order": 0,
                "timestamp": "2026-10-05T10:00:00+00:00",
                "message_data": {},
                "uuid": "",
            }
        ),
    ],
    ids=["not-json", "missing-fields", "no-uuid"],
)
def test_malformed_message_is_skipped_and_the_others_stored(graph, store, malformed_payload):
    session = _session(graph)
    payload = _payload(session.id)

    store.persist_batch([malformed_payload, payload])

    assert _stored_uuids(session) == [_uuid_of(payload)]


def test_graph_end_in_the_same_batch_creates_the_subgraph_sessions(graph, child_graph, store):
    session = _session(graph)
    execution_id = str(uuid4())
    nested_execution_id = str(uuid4())
    payloads = [
        *_subgraph_messages(session, child_graph, execution_id),
        _payload(
            session.id,
            "agent",
            subgraph_execution_ids=[nested_execution_id, execution_id],
        ),
        _payload(session.id, "graph_end"),
    ]

    store.persist_batch(payloads)

    child_session = Session.objects.get(parent_session=session)
    assert child_session.graph_id == child_graph.id
    assert child_session.status == Session.SessionStatus.END
    assert child_session.variables == {"answer": "!"}
    assert child_session.token_usage["total_tokens"] == 10
    copies = list(GraphSessionMessage.objects.filter(session=child_session).order_by("id"))
    assert [copy.message_data["subgraph_execution_ids"] for copy in copies] == [
        [],
        [nested_execution_id],
    ]
    assert [
        str(copy.parent_subgraph_execution_id) if copy.parent_subgraph_execution_id else None
        for copy in copies
    ] == [None, nested_execution_id]


def test_node_type_is_stored_and_copied_into_subgraph_sessions(graph, child_graph, store):
    session = _session(graph)
    start, inner, finish = _subgraph_messages(session, child_graph, str(uuid4()))
    inner = json.dumps({**json.loads(inner), "node_type": "AGENT"})

    store.persist_batch([start, inner, finish, _payload(session.id, "graph_end")])

    stored = GraphSessionMessage.objects.get(session=session, uuid=_uuid_of(inner))
    [copy] = GraphSessionMessage.objects.filter(
        session__parent_session=session, message_data__message_type="agent"
    )
    assert (stored.node_type, copy.node_type) == ("AGENT", "AGENT")


def test_subgraph_copies_are_not_truncated_for_a_large_run(graph, child_graph, store):
    session = _session(graph)
    execution_id = str(uuid4())
    GraphSessionMessage.objects.bulk_create(
        [
            GraphSessionMessage(
                session=session,
                created_at=timezone.now(),
                execution_order=index,
                message_data={"message_type": "agent", "subgraph_execution_ids": [execution_id]},
                uuid=uuid4(),
                parent_subgraph_execution_id=execution_id,
            )
            for index in range(1200)
        ]
    )

    store.persist_batch(
        [*_subgraph_messages(session, child_graph, execution_id), _payload(session.id, "graph_end")]
    )

    child_session = Session.objects.get(parent_session=session)
    assert GraphSessionMessage.objects.filter(session=child_session).count() == 1201


def test_token_usage_of_a_session_is_summed_across_batches(graph, store, redis_client):
    session = _session(graph)
    other_session = _session(graph)

    store.persist_batch(
        [
            _payload(session.id, **_usage(100, 0.25)),
            _payload(session.id, "start"),
            _payload(other_session.id, **_usage(1)),
        ]
    )
    store.persist_batch([_payload(session.id, "finish", output=_usage(50, 0.5))])

    stored = redis_client.hgetall(f"session:{session.id}:token_usage")
    assert int(stored["total_tokens"]) == 150
    assert int(stored["prompt_tokens"]) == 148
    assert int(stored["successful_requests"]) == 2
    assert float(stored["total_cost_usd"]) == pytest.approx(0.75)
    assert redis_client.hget(f"session:{other_session.id}:token_usage", "total_tokens") == "1"


def test_every_addition_keeps_the_usage_keys_alive_for_another_day(graph, store, redis_client):
    session = _session(graph)
    total_key = f"session:{session.id}:token_usage"
    counted_key = f"session:{session.id}:token_usage:counted_messages"
    store.persist_batch([_payload(session.id, **_usage(100))])
    # As if the run had been going for almost a day.
    redis_client.expire(total_key, 5)
    redis_client.expire(counted_key, 5)

    store.persist_batch([_payload(session.id, **_usage(1))])

    assert redis_client.ttl(total_key) > 23 * 60 * 60
    assert redis_client.ttl(counted_key) > 23 * 60 * 60
    assert redis_client.hget(total_key, "total_tokens") == "101"


def test_usage_of_rows_an_earlier_attempt_stored_is_counted_on_redelivery(
    graph, store, redis_client
):
    session = _session(graph)
    payloads = [_payload(session.id, **_usage(100)), _payload(session.id, **_usage(20))]
    store.persist_batch(payloads)
    # The rows are committed, but their usage never reached Redis (restarted empty).
    redis_client.flushall()

    store.persist_batch([*payloads, _payload(session.id, "graph_end")])

    session.refresh_from_db()
    assert session.token_usage["total_tokens"] == 120
    assert redis_client.hget(f"session:{session.id}:token_usage", "total_tokens") == "120"


def test_redelivery_after_a_crash_before_storing_the_total_stores_it_counted_once(
    graph, store, redis_client, monkeypatch
):
    session = _session(graph, status=Session.SessionStatus.ERROR)
    payloads = [_payload(session.id, **_usage(30))]

    def crash(*args, **kwargs):
        raise OperationalError("connection lost")

    with monkeypatch.context() as patch:
        patch.setattr(store, "_store_token_totals", crash)
        with pytest.raises(OperationalError):
            store.persist_batch(payloads)
    store.persist_batch(payloads)

    session.refresh_from_db()
    assert session.token_usage["total_tokens"] == 30
    assert session.status_data["total_token_usage"]["total_tokens"] == 30


def test_graph_end_is_published_when_creating_subgraph_sessions_fails_for_good(
    graph, store, redis_client
):
    session = _session(graph)
    subscriber = redis_client.pubsub()
    subscriber.subscribe(f"session:update:{session.id}:messages")
    payloads = [
        # Not a graph id: creating its session can never succeed.
        _payload(
            session.id,
            "subgraph_start",
            subgraph_execution_id=str(uuid4()),
            subgraph_id="not-a-graph-id",
            subgraph_execution_ids=[],
        ),
        _payload(session.id, **_usage(7)),
        _payload(session.id, "graph_end"),
    ]

    store.persist_batch(payloads)

    published = _published(subscriber)
    subscriber.close()
    session.refresh_from_db()
    assert [message["data"] for message in published] == payloads
    assert not Session.objects.filter(parent_session=session).exists()
    assert session.token_usage["total_tokens"] == 7


def test_transient_failure_creating_subgraph_sessions_holds_back_graph_end(
    graph, store, redis_client, monkeypatch
):
    session = _session(graph)
    subscriber = redis_client.pubsub()
    subscriber.subscribe(f"session:update:{session.id}:messages")

    def database_unavailable(root_session_id):
        raise OperationalError("server closed the connection")

    monkeypatch.setattr(store, "create_subgraph_sessions", database_unavailable)

    with pytest.raises(OperationalError):
        store.persist_batch([_payload(session.id, "graph_end")])

    published = _published(subscriber)
    subscriber.close()
    assert published == []


def test_running_session_total_is_left_to_the_status_handler(graph, store):
    session = _session(graph)

    store.persist_batch([_payload(session.id, **_usage(100))])

    session.refresh_from_db()
    assert session.token_usage == {}


@pytest.fixture
def status_pubsub(monkeypatch, redis_client):
    monkeypatch.setattr(redis_pubsub.RedisPubSub, "_create_redis_client", lambda self: redis_client)
    # close_old_connections() would drop the test's transactional DB connection.
    monkeypatch.setattr(redis_pubsub, "close_old_connections", lambda: None)
    yield redis_pubsub.RedisPubSub()


def _status(session_id, status):
    return {
        "data": json.dumps({"session_id": session_id, "status": status, "status_data": {}})
    }


def test_end_status_before_graph_end_still_ends_with_the_full_total(
    graph, store, redis_client, status_pubsub
):
    session = _session(graph)
    redis_client.set(f"session:{session.id}:final_variables", json.dumps({"result": "done"}))
    store.persist_batch([_payload(session.id, **_usage(100))])

    # The status channel is not held back by the stream's backlog.
    status_pubsub.session_status_handler(_status(session.id, "end"))
    session.refresh_from_db()
    total_at_end_status = session.token_usage["total_tokens"]
    store.persist_batch([_payload(session.id, **_usage(50)), _payload(session.id, "graph_end")])

    session.refresh_from_db()
    assert total_at_end_status == 100
    assert session.status == Session.SessionStatus.END
    assert session.token_usage["total_tokens"] == 150
    assert session.status_data["total_token_usage"]["total_tokens"] == 150
    assert session.status_data["variables"] == {"result": "done"}


def test_graph_end_before_end_status_also_ends_with_the_full_total(
    graph, store, status_pubsub
):
    session = _session(graph)
    store.persist_batch([_payload(session.id, **_usage(100)), _payload(session.id, "graph_end")])

    status_pubsub.session_status_handler(_status(session.id, "end"))

    session.refresh_from_db()
    assert session.status == Session.SessionStatus.END
    assert session.token_usage["total_tokens"] == 100
    assert session.status_data["total_token_usage"]["total_tokens"] == 100


def test_usage_arriving_after_an_error_status_reaches_the_stored_total(
    graph, store, status_pubsub
):
    session = _session(graph)
    store.persist_batch([_payload(session.id, **_usage(100))])
    status_pubsub.session_status_handler(_status(session.id, "error"))

    store.persist_batch([_payload(session.id, **_usage(30))])

    session.refresh_from_db()
    assert session.status == Session.SessionStatus.ERROR
    assert session.token_usage["total_tokens"] == 130
    assert session.status_data["total_token_usage"]["total_tokens"] == 130


def _old_subgraph_copies(root_rows: list[dict]) -> dict[str, dict]:
    """The subgraph membership rule as it was before the rows were selected by
    ``parent_subgraph_execution_id``: kept here as the reference to compare with."""
    start_messages = {}
    for message_data in root_rows:
        if message_data.get("message_type") == "subgraph_start":
            start_messages[message_data["subgraph_execution_id"]] = message_data
    expected = {}
    for execution_id in start_messages:
        subgraph_rows = [
            message_data
            for message_data in root_rows
            if execution_id in (message_data.get("subgraph_execution_ids") or [])
        ]
        expected[execution_id] = {
            "copies": [
                {
                    **message_data,
                    "subgraph_execution_ids": message_data["subgraph_execution_ids"][
                        : message_data["subgraph_execution_ids"].index(execution_id)
                    ],
                }
                for message_data in subgraph_rows
            ],
            "total_tokens": sum(
                (message_data.get("token_usage") or {}).get("total_tokens", 0)
                for message_data in subgraph_rows
            ),
        }
    return expected


def test_nested_subgraph_sessions_get_the_same_messages_as_the_old_membership_rule(
    graph, default_org, store
):
    session = _session(graph)
    graphs = {
        name: Graph.objects.create(name=f"subgraph-{name}", org=default_org)
        for name in ("outer", "middle", "inner", "sibling", "unfinished")
    }
    execution_ids = {name: str(uuid4()) for name in graphs}
    outer, middle, inner, sibling, unfinished = (execution_ids[name] for name in graphs)

    def start(name, *ancestors):
        return _payload(
            session.id,
            "subgraph_start",
            subgraph_execution_id=execution_ids[name],
            subgraph_id=graphs[name].id,
            input={"in": name},
            subgraph_execution_ids=list(ancestors),
            state={"large": "x" * 1000},
        )

    def finish(name, *ancestors):
        return _payload(
            session.id,
            "subgraph_finish",
            subgraph_execution_id=execution_ids[name],
            output={"out": name},
            subgraph_execution_ids=list(ancestors),
        )

    def inside(*ancestors, tokens=0):
        usage = _usage(tokens) if tokens else {}
        return _payload(session.id, "agent", subgraph_execution_ids=list(ancestors), **usage)

    # crew tags a message with the subgraphs it runs in, innermost first.
    payloads = [
        _payload(session.id, "agent", **_usage(1000)),
        start("outer"),
        inside(outer, tokens=1),
        start("middle", outer),
        inside(middle, outer, tokens=10),
        start("inner", middle, outer),
        inside(inner, middle, outer, tokens=100),
        finish("inner", middle, outer),
        inside(middle, outer, tokens=1000),
        finish("middle", outer),
        finish("outer"),
        start("sibling"),
        inside(sibling, tokens=5),
        finish("sibling"),
        start("unfinished"),
        inside(unfinished, tokens=3),
        _payload(session.id, "agent", **_usage(2000)),
        _payload(session.id, "graph_end"),
    ]

    store.persist_batch(payloads)

    root_rows = list(
        GraphSessionMessage.objects.filter(session=session)
        .order_by("id")
        .values_list("message_data", flat=True)
    )
    expected = _old_subgraph_copies(root_rows)
    sessions_by_execution_id = {
        execution_id: Session.objects.get(graph=graphs[name], parent_session__isnull=False)
        for name, execution_id in execution_ids.items()
    }
    actual = {
        execution_id: {
            "copies": list(
                GraphSessionMessage.objects.filter(session=child_session)
                .order_by("id")
                .values_list("message_data", flat=True)
            ),
            "total_tokens": child_session.token_usage["total_tokens"],
        }
        for execution_id, child_session in sessions_by_execution_id.items()
    }
    assert actual == expected
    assert expected[outer]["total_tokens"] == 1111
    assert {
        name: (
            sessions_by_execution_id[execution_ids[name]].parent_session_id,
            sessions_by_execution_id[execution_ids[name]].status,
            sessions_by_execution_id[execution_ids[name]].variables,
        )
        for name in graphs
    } == {
        "outer": (session.id, Session.SessionStatus.END, {"out": "outer"}),
        "middle": (
            sessions_by_execution_id[outer].id,
            Session.SessionStatus.END,
            {"out": "middle"},
        ),
        "inner": (
            sessions_by_execution_id[middle].id,
            Session.SessionStatus.END,
            {"out": "inner"},
        ),
        "sibling": (session.id, Session.SessionStatus.END, {"out": "sibling"}),
        "unfinished": (session.id, Session.SessionStatus.ERROR, {"in": "unfinished"}),
    }
    assert sessions_by_execution_id[inner].status_data == {
        "variables": {"out": "inner"},
        "total_token_usage": sessions_by_execution_id[inner].token_usage,
    }


def test_root_session_without_subgraphs_costs_one_query_to_finish(
    graph, store, django_assert_num_queries
):
    session = _session(graph)
    store.persist_batch([_payload(session.id, **_usage(5)) for _ in range(3)])

    with django_assert_num_queries(1):
        store.create_subgraph_sessions(session.id)

    assert not Session.objects.filter(parent_session=session).exists()


def _in_another_connection(work) -> dict:
    """Run ``work`` on a second database connection, as a concurrent worker would."""
    outcome = {}

    def run():
        try:
            outcome["result"] = work()
        except Exception as error:
            outcome["error"] = error
        finally:
            connection.close()

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(timeout=30)
    return outcome


def _insert_message_waiting_at_most_two_seconds(session_id):
    def insert():
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '2s'")
            GraphSessionMessage.objects.create(
                session_id=session_id,
                created_at=timezone.now(),
                message_data={"message_type": "agent"},
                uuid=uuid4(),
            )
        return "inserted"

    return insert


@pytest.mark.django_db(transaction=True)
def test_storing_a_token_total_does_not_block_message_inserts_of_that_session(
    graph, store, monkeypatch
):
    session = _session(graph, status=Session.SessionStatus.END)
    read_total = store.token_usage_counter.read
    outcomes = []

    def insert_while_the_session_is_locked(session_id):
        outcomes.append(_in_another_connection(_insert_message_waiting_at_most_two_seconds(session_id)))
        return read_total(session_id)

    monkeypatch.setattr(store.token_usage_counter, "read", insert_while_the_session_is_locked)

    store.persist_batch([_payload(session.id, **_usage(5))])

    assert outcomes == [{"result": "inserted"}]


@pytest.mark.django_db(transaction=True)
def test_status_handler_does_not_block_message_inserts_of_that_session(
    graph, status_pubsub, monkeypatch
):
    session = _session(graph)
    read_total = redis_pubsub.SessionTokenUsageCounter.read
    outcomes = []

    def insert_while_the_session_is_locked(counter, session_id):
        outcomes.append(_in_another_connection(_insert_message_waiting_at_most_two_seconds(session_id)))
        return read_total(counter, session_id)

    monkeypatch.setattr(
        redis_pubsub.SessionTokenUsageCounter, "read", insert_while_the_session_is_locked
    )

    status_pubsub.session_status_handler(_status(session.id, "run"))

    session.refresh_from_db()
    assert outcomes == [{"result": "inserted"}]
    assert session.status == Session.SessionStatus.RUN


@pytest.mark.django_db(transaction=True)
def test_status_handler_persists_results_after_releasing_the_session_lock(
    graph, status_pubsub, monkeypatch
):
    session = _session(graph)
    outcomes = []

    def lock_session_without_waiting():
        with transaction.atomic():
            Session.objects.select_for_update(no_key=True, nowait=True).get(pk=session.pk)
        return "locked"

    def persist_session_results(session, final_variables):
        outcomes.append(_in_another_connection(lock_session_without_waiting))

    monkeypatch.setattr(
        status_pubsub.persistent_variables_service,
        "persist_session_results",
        persist_session_results,
    )

    status_pubsub.session_status_handler(_status(session.id, "end"))

    session.refresh_from_db()
    assert outcomes == [{"result": "locked"}]
    assert session.status == Session.SessionStatus.END


def test_file_data_is_published_as_a_preview_and_stored_whole(graph, store, redis_client):
    session = _session(graph)
    subscriber = redis_client.pubsub()
    subscriber.subscribe(f"session:update:{session.id}:messages")
    file_data = "A" * 10_000
    payload = _payload(
        session.id,
        message_type="start",
        input={"files": [{"name": "report.pdf", "base64_data": file_data}]},
    )

    store.persist_batch([payload])

    published = _published(subscriber)
    subscriber.close()
    published_message = json.loads(published[0]["data"])
    assert published_message["message_data"]["input"]["files"] == [
        {"name": "report.pdf", "base64_data": "A" * 50}
    ]
    stored = GraphSessionMessage.objects.get(session=session)
    assert stored.message_data["input"]["files"][0]["base64_data"] == file_data
