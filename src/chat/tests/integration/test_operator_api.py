import asyncio
import base64
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from application.orchestrators.events import conversation_summary
from application.ports import CallerCredentials
from application.tokens import issue_visitor_token
from common.utils import new_id, utcnow
from domain.enums import Mode, Role, Stream
from bootstrap.di import bindings as build_bindings
from domain.errors import AliasReservedError, BotNameTakenError, UpstreamUnavailableError
from domain.models import VisitorToken
from infrastructure.database.models import OperatorProfileRow, VisitorTokenRow
from infrastructure.database.repositories import OperatorAliasRepository
from presentation.rest.controllers.operator import PAGE_SIZE
from application.orchestrators.budgets import NEW_DESK_RULES
from presentation.rest.schemas.operator import ConversationOutput
from sqlalchemy import func, select
from tests.factories import make_binding, make_closed, make_conversation
from tests.infrastructure.test_django_client import CHAT_FLOW

BASE = "/chat/operator/v1"
ORIGIN = "https://example.com"
ALL = ["create", "read", "update", "delete", "use"]


@pytest.fixture
def people(django):
    """admin: all chats actions and flows:read in org 1 and 2; agent: read+use in org 1 only;
    viewer: member of org 1 with nothing; binder: all chats actions in org 1 but no flows:read."""
    django.users["admin"] = {"active": True, "user_id": 1, "email": "a@x", "scopes": [], "org_ids": [1, 2], "is_superadmin": False}
    django.users["agent"] = {"active": True, "user_id": 2, "email": "b@x", "scopes": [], "org_ids": [1], "is_superadmin": False}
    django.users["viewer"] = {"active": True, "user_id": 3, "email": "c@x", "scopes": [], "org_ids": [1], "is_superadmin": False}
    django.users["binder"] = {"active": True, "user_id": 4, "email": "d@x", "scopes": [], "org_ids": [1], "is_superadmin": False}
    django.permissions[("admin", 1)] = {"chats": ALL, "flows": ["read"]}
    django.permissions[("admin", 2)] = {"chats": ALL, "flows": ["read"]}
    django.permissions[("binder", 1)] = {"chats": ALL}
    django.permissions[("agent", 1)] = {"chats": ["read", "use"]}
    django.permissions[("viewer", 1)] = {"chats": []}
    django.graphs[5] = CHAT_FLOW
    django.graphs[6] = {"org_id": 2, **{k: v for k, v in CHAT_FLOW.items() if k != "org_id"}}
    django.graphs[7] = {"org_id": 1, "start_variables": {"variables": {}}, "output_map": {"x": "y"}}


def h(user, org=1):
    return {"Authorization": f"Bearer {user}", "X-Organization-Id": str(org)}


NEW_BINDING = {"name": "Support", "graph_id": 5, "allowed_origins": [ORIGIN], "identity_mode": "anonymous"}


# ---- auth and scoping --------------------------------------------------------------------------

async def test_auth_failures(client, people):
    assert (await client.get(f"{BASE}/bindings")).status_code == 401
    assert (await client.get(f"{BASE}/bindings", headers=h("nobody"))).status_code == 401
    assert (await client.get(f"{BASE}/bindings", headers={"Authorization": "Bearer admin"})).status_code == 400
    assert (await client.get(f"{BASE}/bindings", headers=h("agent", org=2))).status_code == 404
    forbidden = await client.post(f"{BASE}/bindings", json=NEW_BINDING, headers=h("agent"))
    assert (forbidden.status_code, forbidden.json()["code"]) == (403, "forbidden")
    assert (await client.get(f"{BASE}/bindings", headers=h("viewer"))).status_code == 403


async def test_bindings_are_org_scoped(client, people):
    created = await client.post(f"{BASE}/bindings", json=NEW_BINDING, headers=h("admin", org=1))
    assert created.status_code == 201, created.text
    binding_id = created.json()["id"]
    assert [b["id"] for b in (await client.get(f"{BASE}/bindings", headers=h("admin", org=1))).json()] == [binding_id]
    assert (await client.get(f"{BASE}/bindings", headers=h("admin", org=2))).json() == []
    assert (await client.get(f"{BASE}/bindings/{binding_id}", headers=h("admin", org=2))).status_code == 404
    assert (await client.patch(f"{BASE}/bindings/{binding_id}", json={"name": "x"}, headers=h("admin", org=2))).status_code == 404
    assert (await client.delete(f"{BASE}/bindings/{binding_id}", headers=h("admin", org=2))).status_code == 404
    assert (await client.delete(f"{BASE}/bindings/{binding_id}", headers=h("admin", org=1))).status_code == 204


# ---- bindings and the contract check ---------------------------------------------------------

def _graph_reads(django) -> list:
    return [request for request in django.requests if request.url.path.startswith("/api/graphs/")]


async def test_create_reads_the_graph_with_the_callers_token_and_org(client, people, django):
    created = await client.post(f"{BASE}/bindings", json=NEW_BINDING, headers=h("admin"))
    assert created.status_code == 201
    (read,) = _graph_reads(django)
    assert (read.headers["Authorization"], read.headers["X-Organization-Id"]) == ("Bearer admin", "1")
    assert "X-Api-Key" not in read.headers


async def test_create_without_flows_read_is_forbidden_and_stores_nothing(client, people):
    refused = await client.post(f"{BASE}/bindings", json=NEW_BINDING, headers=h("binder"))
    assert (refused.status_code, refused.json()["code"]) == (403, "flow_forbidden")
    assert "flows:read" in refused.json()["message"]
    assert (await client.get(f"{BASE}/bindings", headers=h("binder"))).json() == []


async def test_create_answers_the_same_for_another_orgs_graph_and_a_missing_one(client, people):
    foreign = await client.post(f"{BASE}/bindings", json={**NEW_BINDING, "graph_id": 6}, headers=h("admin"))
    missing = await client.post(f"{BASE}/bindings", json={**NEW_BINDING, "graph_id": 999}, headers=h("admin"))
    assert foreign.status_code == missing.status_code == 400
    assert foreign.json() == missing.json() == {"code": "unknown_flow", "message": "The flow does not exist in this organization."}
    assert (await client.get(f"{BASE}/bindings", headers=h("admin"))).json() == []


async def test_patch_to_a_new_graph_without_flows_read_is_forbidden_and_stores_nothing(client, people, django):
    django.graphs[8] = {**CHAT_FLOW}
    binding = (await client.post(f"{BASE}/bindings", json=NEW_BINDING, headers=h("admin"))).json()
    refused = await client.patch(f"{BASE}/bindings/{binding['id']}", json={"graph_id": 8, "name": "Moved"}, headers=h("binder"))
    assert (refused.status_code, refused.json()["code"]) == (403, "flow_forbidden")
    stored = (await client.get(f"{BASE}/bindings/{binding['id']}", headers=h("admin"))).json()
    assert (stored["graph_id"], stored["name"]) == (5, "Support")
    (_, patch_read) = _graph_reads(django)
    assert (patch_read.headers["Authorization"], patch_read.headers["X-Organization-Id"]) == ("Bearer binder", "1")


async def test_patch_to_another_orgs_graph_is_unknown_flow_and_stores_nothing(client, people):
    binding = (await client.post(f"{BASE}/bindings", json=NEW_BINDING, headers=h("admin"))).json()
    refused = await client.patch(f"{BASE}/bindings/{binding['id']}", json={"graph_id": 6}, headers=h("admin"))
    assert (refused.status_code, refused.json()["code"]) == (400, "unknown_flow")
    assert (await client.get(f"{BASE}/bindings/{binding['id']}", headers=h("admin"))).json()["graph_id"] == 5


async def test_create_checks_contract_and_hides_secret_on_get(client, people):
    created = await client.post(f"{BASE}/bindings", json={**NEW_BINDING, "identity_mode": "signed"}, headers=h("admin"))
    body = created.json()
    assert body["contract_errors"] == [] and body["is_active"] is True and len(body["identity_secret"]) >= 32 and len(body["public_key"]) >= 24
    fetched = (await client.get(f"{BASE}/bindings/{body['id']}", headers=h("admin"))).json()
    assert "identity_secret" not in fetched and fetched["identity_mode"] == "signed"
    bad = await client.post(f"{BASE}/bindings", json={**NEW_BINDING, "graph_id": 7}, headers=h("admin"))
    assert bad.status_code == 201 and bad.json()["is_active"] is False and len(bad.json()["contract_errors"]) == 3
    # `is_active` is no longer input: a failing flow is created paused whatever the body says.
    asked_active = await client.post(f"{BASE}/bindings", json={**NEW_BINDING, "graph_id": 7, "is_active": True}, headers=h("admin"))
    assert asked_active.status_code == 201 and asked_active.json()["is_active"] is False and len(asked_active.json()["contract_errors"]) == 3
    unknown = await client.post(f"{BASE}/bindings", json={**NEW_BINDING, "graph_id": 6}, headers=h("admin"))
    assert (unknown.status_code, unknown.json()["code"]) == (400, "unknown_flow")


async def test_update_rotate_snippet(client, people, settings):
    binding = (await client.post(f"{BASE}/bindings", json=NEW_BINDING, headers=h("admin"))).json()
    updated = await client.patch(f"{BASE}/bindings/{binding['id']}", json={"max_turns": 3}, headers=h("admin"))
    assert updated.status_code == 200 and updated.json()["is_active"] is True and updated.json()["max_turns"] == 3
    noop = await client.patch(f"{BASE}/bindings/{binding['id']}", json={}, headers=h("admin"))
    assert noop.status_code == 200 and "identity_secret" not in noop.json()
    # A failing flow is saved, and the save pauses the live binding.
    moved = await client.patch(f"{BASE}/bindings/{binding['id']}", json={"graph_id": 7}, headers=h("admin"))
    assert moved.status_code == 200 and moved.json()["graph_id"] == 7 and moved.json()["is_active"] is False
    assert len(moved.json()["contract_errors"]) == 3
    signed = await client.patch(f"{BASE}/bindings/{binding['id']}", json={"identity_mode": "signed"}, headers=h("admin"))
    assert signed.status_code == 200 and len(signed.json()["identity_secret"]) >= 32
    rotated = await client.post(f"{BASE}/bindings/{binding['id']}/rotate-key", headers=h("admin"))
    assert rotated.status_code == 200 and rotated.json()["public_key"] != binding["public_key"]
    snippet = await client.get(f"{BASE}/bindings/{binding['id']}/snippet", headers=h("admin"))
    assert snippet.status_code == 200
    assert snippet.json()["public_key"] == rotated.json()["public_key"] and settings.CHAT_PUBLIC_BASE_URL in snippet.json()["snippet"]
    assert (await client.post(f"{BASE}/bindings/{binding['id']}/rotate-key", headers=h("agent"))).status_code == 403


# ---- visitor token revocation -------------------------------------------------------------------

async def _visitor(client, public_key):
    created = (await client.post("/chat/public/v1/conversations", json={"public_key": public_key}, headers={"Origin": ORIGIN})).json()
    return f"/chat/public/v1/conversations/{created['conversation_id']}", {"Authorization": f"Bearer {created['visitor_token']}", "Origin": ORIGIN}


async def _live_bindings(client):
    first = (await client.post(f"{BASE}/bindings", json=NEW_BINDING, headers=h("admin"))).json()
    second = (await client.post(f"{BASE}/bindings", json={**NEW_BINDING, "name": "Other"}, headers=h("admin"))).json()
    return first, second


async def test_rotate_key_revokes_that_bindings_visitor_tokens_only(client, people):
    first, second = await _live_bindings(client)
    revoked_url, revoked = await _visitor(client, first["public_key"])
    kept_url, kept = await _visitor(client, second["public_key"])
    assert (await client.post(f"{BASE}/bindings/{first['id']}/rotate-key", headers=h("admin"))).status_code == 200
    refused = await client.get(revoked_url, headers=revoked)
    assert (refused.status_code, refused.json()["code"]) == (401, "invalid_token")
    assert (await client.get(kept_url, headers=kept)).status_code == 200


async def test_switching_identity_mode_revokes_that_bindings_visitor_tokens_only(client, people):
    first, second = await _live_bindings(client)
    revoked_url, revoked = await _visitor(client, first["public_key"])
    kept_url, kept = await _visitor(client, second["public_key"])
    unchanged = await client.patch(f"{BASE}/bindings/{first['id']}", json={"identity_mode": "anonymous", "name": "Same mode"}, headers=h("admin"))
    assert unchanged.status_code == 200
    assert (await client.get(revoked_url, headers=revoked)).status_code == 200  # the same mode revokes nothing
    switched = await client.patch(f"{BASE}/bindings/{first['id']}", json={"identity_mode": "signed"}, headers=h("admin"))
    assert switched.status_code == 200
    refused = await client.get(revoked_url, headers=revoked)
    assert (refused.status_code, refused.json()["code"]) == (401, "invalid_token")
    assert (await client.get(kept_url, headers=kept)).status_code == 200


async def test_a_test_conversation_reads_on_an_inactive_binding(client, people):
    binding = (await client.post(f"{BASE}/bindings", json=NEW_BINDING, headers=h("admin"))).json()
    assert (await client.post(f"{BASE}/bindings/{binding['id']}/pause", headers=h("admin"))).json()["is_active"] is False
    test = (await client.post(f"{BASE}/bindings/{binding['id']}/test-conversation", headers=h("admin"))).json()
    url, headers = f"/chat/public/v1/conversations/{test['conversation']['id']}", {"Authorization": f"Bearer {test['visitor_token']}"}
    assert (await client.get(url, headers=headers)).status_code == 200
    assert (await client.get(f"{url}/messages", headers=headers)).status_code == 200
    ticket = await client.post(f"{url}/stream-ticket", headers=headers)
    assert ticket.status_code == 201


# ---- conversations, inbox, handoff -------------------------------------------------------------

async def _active_binding(client):
    created = (await client.post(f"{BASE}/bindings", json=NEW_BINDING, headers=h("admin"))).json()
    assert created["is_active"] is True
    return created


async def test_test_conversation_and_inbox(client, people, django, uow_factory):
    binding = await _active_binding(client)
    test = await client.post(f"{BASE}/bindings/{binding['id']}/test-conversation", headers=h("admin"))
    assert test.status_code == 201
    created, token = test.json()["conversation"], test.json()["visitor_token"]
    assert set(test.json()) == {"visitor_token", "conversation"}
    conversation_id = created["id"]
    assert created["is_test"] is True
    assert created["mode"] == "bot" and created["state"] == "idle" and created["last_message_at"] is None
    # The operator inbox upserts from this stream, so the new row must appear before any message.
    async with uow_factory() as uow:
        inbox = await uow.events.replay(Stream.INBOX, org_id=1, after_seq=None)
    announced = [e.payload for e in inbox if e.type == "conversation.updated" and e.conversation_id == UUID(conversation_id)]
    assert len(announced) == 1 and announced[0]["is_test"] is True
    sent = await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json={"content": "hello"}, headers={"Authorization": f"Bearer {token}"})
    assert sent.status_code == 202 and sent.json()["state"] == "processing"
    listed = await client.get(f"{BASE}/conversations?section=test", headers=h("admin"))
    assert listed.status_code == 200 and len(listed.json()["results"]) == 1 and listed.json()["next_cursor"] is None
    assert (await client.get(f"{BASE}/conversations?section=bot", headers=h("agent"))).json()["results"] == []
    item = listed.json()["results"][0]
    assert item["id"] == conversation_id and item["state"] == "processing" and item["is_test"] and item["last_message_preview"] == "hello"
    assert (await client.get(f"{BASE}/conversations?section=test", headers=h("admin", org=2))).json() == {"results": [], "next_cursor": None}
    messages = await client.get(f"{BASE}/conversations/{conversation_id}/messages", headers=h("agent"))
    assert messages.status_code == 200 and messages.json()[0]["session_id"] == 100
    assert (await client.get(f"{BASE}/conversations/{conversation_id}/messages", headers=h("admin", org=2))).status_code == 404
    assert (await client.post(f"{BASE}/bindings/{binding['id']}/test-conversation", headers=h("viewer"))).status_code == 403


async def test_only_desk_builders_get_the_snippet_and_start_list_and_rejoin_tests(client, people, django):
    django.users["builder"] = {"active": True, "user_id": 5, "email": "e@x", "scopes": [], "org_ids": [1], "is_superadmin": False}
    django.permissions[("builder", 1)] = {"chats": ["read", "update"]}
    binding = await _active_binding(client)
    started = await client.post(f"{BASE}/bindings/{binding['id']}/test-conversation", headers=h("builder"))
    assert started.status_code == 201
    conversation_id = started.json()["conversation"]["id"]
    assert (await client.get(f"{BASE}/conversations?section=test", headers=h("builder"))).status_code == 200
    assert (await client.post(f"{BASE}/conversations/{conversation_id}/visitor-token", headers=h("builder"))).status_code == 201
    assert (await client.get(f"{BASE}/bindings/{binding['id']}/snippet", headers=h("builder"))).status_code == 200
    # read + use is support work: no tests and no snippet.
    for refused in (
        await client.get(f"{BASE}/bindings/{binding['id']}/snippet", headers=h("agent")),
        await client.post(f"{BASE}/bindings/{binding['id']}/test-conversation", headers=h("agent")),
        await client.get(f"{BASE}/conversations?section=test", headers=h("agent")),
        await client.post(f"{BASE}/conversations/{conversation_id}/visitor-token", headers=h("agent")),
    ):
        assert (refused.status_code, refused.json()["code"]) == (403, "forbidden")
    assert (await client.get(f"{BASE}/conversations?section=bot", headers=h("agent"))).status_code == 200


async def test_claim_stops_run_release_and_reply(client, people, django, uow_factory):
    binding = await _active_binding(client)
    test = (await client.post(f"{BASE}/bindings/{binding['id']}/test-conversation", headers=h("admin"))).json()
    conversation_id, token = test["conversation"]["id"], test["visitor_token"]
    visitor = {"Authorization": f"Bearer {token}"}
    await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json={"content": "help"}, headers=visitor)

    claimed = await client.post(f"{BASE}/conversations/{conversation_id}/claim", json={}, headers=h("agent"))
    assert claimed.status_code == 200 and claimed.json()["mode"] == "human" and claimed.json()["assigned_operator_id"] == 2
    taken_over_at = await _stored_handoff_at(uow_factory, conversation_id)
    assert taken_over_at is not None and datetime.fromisoformat(claimed.json()["handoff_at"]) == taken_over_at
    assert django.stopped == [100]
    assert (await client.get(f"/chat/public/v1/conversations/{conversation_id}", headers=visitor)).json() == {"mode": "human", "state": "idle", "bot_display_name": "Support", "operator_display_name": "Support", "status": "open", "close_reason": None, "closed_at": None}

    other = await client.post(f"{BASE}/conversations/{conversation_id}/claim", json={}, headers=h("admin"))
    assert (other.status_code, other.json()["code"]) == (409, "claimed_by_other")
    not_assigned = await client.post(f"{BASE}/conversations/{conversation_id}/messages", json={"content": "mine"}, headers=h("admin"))
    assert (not_assigned.status_code, not_assigned.json()["code"]) == (409, "not_assigned")
    forced = await client.post(f"{BASE}/conversations/{conversation_id}/claim", json={"force": True}, headers=h("admin"))
    assert forced.status_code == 200 and forced.json()["assigned_operator_id"] == 1
    assert await _stored_handoff_at(uow_factory, conversation_id) == taken_over_at

    reply = await client.post(f"{BASE}/conversations/{conversation_id}/messages", json={"content": "Hi, admin here"}, headers=h("admin"))
    assert reply.status_code == 201 and reply.json()["role"] == "operator"
    forwarded = await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json={"content": "thanks"}, headers=visitor)
    assert forwarded.json()["state"] == "forwarded_to_operator"
    stored = (await client.get(f"{BASE}/conversations/{conversation_id}/messages", headers=h("admin"))).json()
    assert {(m["role"], m["author_user_id"]) for m in stored} == {("user", None), ("operator", 1)}

    released = await client.post(f"{BASE}/conversations/{conversation_id}/release", headers=h("admin"))
    assert released.status_code == 200 and released.json()["mode"] == "bot" and released.json()["assigned_operator_id"] is None
    assert released.json()["handoff_at"] is None and await _stored_handoff_at(uow_factory, conversation_id) is None
    again = await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json={"content": "bot?"}, headers=visitor)
    assert again.json()["state"] == "processing"
    async with uow_factory() as uow:
        events = await uow.events.replay(Stream.CONVERSATION, conversation_id=UUID(conversation_id), after_seq=None)
    # operator identity must not reach the visitor-facing conversation stream
    assert [e.payload for e in events if e.type == "mode.changed"] == [{"mode": "human"}, {"mode": "human"}, {"mode": "bot"}]
    async with uow_factory() as uow:
        inbox = await uow.events.replay(Stream.INBOX, org_id=1, after_seq=None)
    updates = [e.payload for e in inbox if e.type == "conversation.updated" and e.conversation_id == UUID(conversation_id)]
    assert 2 in [u["assigned_operator_id"] for u in updates]  # the first claim, by the caller
    # The inbox row is a full conversation row: the frontend upserts it without a refetch.
    assert {"tokens_used", "turns", "tokens_today", "turns_today", "handoff_reason", "is_test", "handoff_at"} <= updates[-1].keys()
    assert updates[-1]["handoff_at"] is None  # released back to the bot
    first_claim = next(u for u in updates if u["assigned_operator_id"] == 2)
    assert datetime.fromisoformat(first_claim["handoff_at"]) == taken_over_at
    run_body = [r for r in django.requests if r.url.path == "/api/run-session/"][-1]
    import json as json_module

    history = json_module.loads(run_body.content)["variables"]["chat_history"]
    assert [m["role"] for m in history] == ["user", "operator", "user"]
    assert (await client.post(f"{BASE}/conversations/{conversation_id}/claim", json={}, headers=h("admin", org=2))).status_code == 404
    assert (await client.post(f"{BASE}/conversations/{conversation_id}/claim", json={}, headers=h("viewer"))).status_code == 403


async def test_list_requires_a_valid_section(client, people):
    assert (await client.get(f"{BASE}/conversations", headers=h("agent"))).status_code == 400
    assert (await client.get(f"{BASE}/conversations?section=awaiting_human", headers=h("agent"))).status_code == 400


async def test_sections_split_by_mode_and_both_are_org_scoped(client, people, uow_factory):
    binding = make_binding(org_id=1, graph_id=5)
    bot = make_conversation(binding, last_message_at=utcnow())
    waiting = make_conversation(binding, mode="awaiting_human", last_message_at=utcnow() - timedelta(hours=1))
    claimed = make_conversation(binding, mode="human", assigned_operator_id=2, last_message_at=utcnow())
    # Test conversations in every mode, a minute apart, newest first: only the test section lists them.
    tests = [
        make_conversation(binding, mode=mode, is_test=True, last_message_at=utcnow() - timedelta(minutes=index))
        for index, mode in enumerate(("bot", "awaiting_human", "human"))
    ]
    await _seed(uow_factory, binding, [bot, waiting, claimed, *tests])
    human = (await client.get(f"{BASE}/conversations?section=human&binding={binding.id}", headers=h("agent"))).json()
    assert [c["id"] for c in human["results"]] == [str(waiting.id), str(claimed.id)]
    assert datetime.fromisoformat(human["results"][0]["handoff_at"]) == waiting.handoff_at
    only_bot = (await client.get(f"{BASE}/conversations?section=bot", headers=h("agent"))).json()
    assert [c["id"] for c in only_bot["results"]] == [str(bot.id)] and only_bot["results"][0]["handoff_at"] is None
    only_tests = (await client.get(f"{BASE}/conversations?section=test", headers=h("admin"))).json()
    assert [c["id"] for c in only_tests["results"]] == [str(c.id) for c in tests]
    assert all(c["is_test"] for c in only_tests["results"])
    for section in ("human", "bot", "test"):
        other_org = await client.get(f"{BASE}/conversations?section={section}", headers=h("admin", org=2))
        assert other_org.json() == {"results": [], "next_cursor": None}


async def test_an_idle_conversation_from_yesterday_lists_zero_usage_today(client, people, uow_factory):
    binding = make_binding(org_id=1, graph_id=5)
    yesterday = utcnow().date() - timedelta(days=1)
    idle = make_conversation(binding, last_message_at=utcnow(), usage_day=yesterday, tokens_used=900, turns=9, tokens_today=300, turns_today=3)
    await _seed(uow_factory, binding, [idle])
    (row,) = (await client.get(f"{BASE}/conversations?section=bot&binding={binding.id}", headers=h("agent"))).json()["results"]
    assert (row["tokens_today"], row["turns_today"], row["tokens_used"], row["turns"]) == (0, 0, 900, 9)
    summary = conversation_summary(idle, {})  # the inbox `conversation.updated` snapshot
    assert (summary["tokens_today"], summary["turns_today"], summary["tokens_used"]) == (0, 0, 900)
    async with uow_factory() as uow:
        stored = await uow.conversations.get(idle.id)
    assert (stored.usage_day, stored.tokens_today) == (yesterday, 300)  # reading writes nothing


# ---- inbox keyset paging -----------------------------------------------------------------------

def _human_order(conversations):
    return [c.id for c in sorted(conversations, key=lambda c: (c.handoff_at, c.id))]


def _bot_order(conversations):
    return [c.id for c in sorted(conversations, key=lambda c: (c.last_message_at, c.id), reverse=True)]


def _spread(binding, count, start=None, group=2, **overrides):
    # Groups share a timestamp, so the id tiebreak is exercised on every page.
    start = start or utcnow()
    return [make_conversation(binding, last_message_at=start - timedelta(seconds=index // group), **overrides) for index in range(count)]


def _spread_handed_off(binding, count, start=None):
    """Awaiting and claimed rows mixed; handoff_at pairs share a timestamp.

    Activity rises with handoff_at, so the bot order (activity DESC, id DESC) is the exact
    reverse of the human order: a human query sorted by activity cannot pass.
    """
    start = start or utcnow() - timedelta(days=1)
    return [
        make_conversation(
            binding,
            mode="awaiting_human" if index % 3 else "human",
            assigned_operator_id=None if index % 3 else 1,
            handoff_at=start + timedelta(seconds=index // 2),
            last_message_at=start + timedelta(hours=1, seconds=index // 2),
        )
        for index in range(count)
    ]


async def _seed(uow_factory, binding, conversations):
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        for conversation in conversations:
            await uow.conversations.add(conversation)
        await uow.commit()


async def _walk(client, query, headers=None):
    """Every id the inbox lists for `query`, following next_cursor; also the page sizes seen."""
    ids, sizes, cursor = [], [], None
    while True:
        params = query + (f"&cursor={cursor}" if cursor else "")
        response = await client.get(f"{BASE}/conversations?{params}", headers=headers or h("agent"))
        assert response.status_code == 200, response.text
        body = response.json()
        ids += [UUID(c["id"]) for c in body["results"]]
        sizes.append(len(body["results"]))
        cursor = body["next_cursor"]
        if cursor is None:
            return ids, sizes


async def test_human_section_walks_first_handed_off_first_across_pages(client, people, uow_factory):
    binding = make_binding(org_id=1, graph_id=5)
    handed_off = _spread_handed_off(binding, 54)
    # Handed off before it said anything: still waits for a human, in its turn.
    silent = make_conversation(binding, mode="awaiting_human", handoff_at=handed_off[20].handoff_at)
    await _seed(uow_factory, binding, [*handed_off, silent, *_spread(binding, 10)])
    ids, sizes = await _walk(client, "section=human")
    assert ids == _human_order([*handed_off, silent])
    assert sizes == [PAGE_SIZE, 55 - PAGE_SIZE]


async def test_an_operator_reply_does_not_move_a_human_row(client, people, uow_factory):
    binding = make_binding(org_id=1, graph_id=5)
    handed_off = _spread_handed_off(binding, 5)
    order = _human_order(handed_off)
    # A middle row: its reply makes it the most recently active, so an activity order in either
    # direction would move it to an end.
    middle = next(c for c in handed_off if c.id == order[2])
    middle.mode, middle.assigned_operator_id = Mode.HUMAN, 2
    await _seed(uow_factory, binding, handed_off)
    reply = await client.post(f"{BASE}/conversations/{middle.id}/messages", json={"content": "On it"}, headers=h("agent"))
    assert reply.status_code == 201
    after, _ = await _walk(client, "section=human")
    assert after == order and after[2] == middle.id


async def test_bot_section_walks_newest_activity_first_and_hides_silent_rows(client, people, uow_factory):
    binding = make_binding(org_id=1, graph_id=5)
    talked = _spread(binding, 75)
    silent = make_conversation(binding)
    await _seed(uow_factory, binding, [*talked, silent, *_spread_handed_off(binding, 5)])
    ids, sizes = await _walk(client, "section=bot")
    assert ids == _bot_order(talked) and sizes == [PAGE_SIZE, 75 - PAGE_SIZE]


async def test_test_section_walks_newest_activity_first_in_every_mode_and_hides_silent_rows(client, people, uow_factory):
    binding = make_binding(org_id=1, graph_id=5)
    tests = [*_spread(binding, 60, is_test=True), *_spread_handed_off(binding, 15)]
    for conversation in tests[60:]:
        conversation.is_test = True
    silent = make_conversation(binding, is_test=True)
    await _seed(uow_factory, binding, [*tests, silent, *_spread(binding, 5), *_spread_handed_off(binding, 5)])
    ids, sizes = await _walk(client, "section=test", headers=h("admin"))
    assert ids == _bot_order(tests) and sizes == [PAGE_SIZE, 75 - PAGE_SIZE]
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize("section", ["human", "bot", "test"])
async def test_exact_page_size_has_no_next_cursor(client, people, uow_factory, section):
    binding = make_binding(org_id=1, graph_id=5)
    rows = _spread_handed_off(binding, PAGE_SIZE) if section == "human" else _spread(binding, PAGE_SIZE, is_test=section == "test")
    await _seed(uow_factory, binding, rows)
    body = (await client.get(f"{BASE}/conversations?section={section}", headers=h("admin"))).json()
    assert len(body["results"]) == PAGE_SIZE and body["next_cursor"] is None


@pytest.mark.parametrize("mode", ["awaiting_human", "human"])
async def test_mode_filter_pages_one_mode_of_the_human_section_in_its_order(client, people, uow_factory, mode):
    binding = make_binding(org_id=1, graph_id=5)
    handed_off = _spread_handed_off(binding, 120)  # 80 awaiting, 40 claimed, interleaved
    silent = make_conversation(binding, mode="awaiting_human")
    # The badge seed reads section=human&mode=awaiting_human: a waiting test must not count.
    waiting_test = make_conversation(binding, mode=mode, is_test=True, last_message_at=utcnow())
    await _seed(uow_factory, binding, [*handed_off, silent, waiting_test, *_spread(binding, 10)])
    wanted = [c for c in [*handed_off, silent] if c.mode == mode]
    ids, sizes = await _walk(client, f"section=human&mode={mode}")
    assert ids == _human_order(wanted)
    assert sizes == [PAGE_SIZE] * (len(wanted) // PAGE_SIZE) + [len(wanted) % PAGE_SIZE]
    other_org, _ = await _walk(client, f"section=human&mode={mode}", headers=h("admin", org=2))
    assert other_org == []


@pytest.mark.parametrize("query", ["section=bot&mode=human", "section=bot&mode=awaiting_human", "section=test&mode=awaiting_human", "section=test&mode=human", "section=human&mode=bot", "section=human&mode=nope", "section=tests"])
async def test_mode_filter_is_refused_outside_the_human_modes(client, people, query):
    refused = await client.get(f"{BASE}/conversations?{query}", headers=h("agent"))
    assert (refused.status_code, refused.json()["code"]) == (400, "validation_error")


async def test_binding_filter_pages_each_section(client, people, uow_factory):
    mine, other = make_binding(org_id=1, graph_id=5), make_binding(org_id=1, graph_id=5)
    my_human, my_bot, my_tests = _spread_handed_off(mine, 60), _spread(mine, 70), _spread(mine, 55, is_test=True)
    await _seed(uow_factory, mine, my_human + my_bot + my_tests)
    await _seed(uow_factory, other, _spread(other, 60) + _spread_handed_off(other, 60) + _spread(other, 60, is_test=True))
    human_ids, human_sizes = await _walk(client, f"section=human&binding={mine.id}")
    bot_ids, bot_sizes = await _walk(client, f"section=bot&binding={mine.id}")
    test_ids, test_sizes = await _walk(client, f"section=test&binding={mine.id}", headers=h("admin"))
    assert human_ids == _human_order(my_human) and human_sizes == [PAGE_SIZE, 60 - PAGE_SIZE]
    assert bot_ids == _bot_order(my_bot) and bot_sizes == [PAGE_SIZE, 70 - PAGE_SIZE]
    assert test_ids == _bot_order(my_tests) and test_sizes == [PAGE_SIZE, 55 - PAGE_SIZE]


def _raw_cursor(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


VALID_KEY = b'"at": "2026-01-01T00:00:00Z", "id": "01a12326-26a7-75e3-b27e-34f28dfb6f8a"'
VALID_CURSOR = _raw_cursor(b"{" + VALID_KEY + b"}")
MALFORMED_CURSORS = {
    "not base64": "not-base64!",
    "empty object": "e30",
    "array": "W10",
    "wrong type": _raw_cursor(b'{"at": "2026-01-01T00:00:00Z", "id": 5}'),
    "naive time": _raw_cursor(b"{" + VALID_KEY.replace(b"00Z", b"00") + b"}"),
    "extra field": _raw_cursor(b"{" + VALID_KEY + b', "org_id": 2}'),
    "old shape": _raw_cursor(b'{"is_awaiting": false, "last_message_at": "2026-01-01T00:00:00Z", "id": "01a12326-26a7-75e3-b27e-34f28dfb6f8a"}'),
    # The stdlib decoder would drop these characters and accept what is left.
    "outside the url-safe alphabet": VALID_CURSOR[:10] + "." + VALID_CURSOR[10:],
    "padding": VALID_CURSOR + "==",
}


@pytest.mark.parametrize("section", ["human", "bot", "test"])
async def test_well_formed_cursor_is_accepted(client, people, section):
    response = await client.get(f"{BASE}/conversations?section={section}&cursor={VALID_CURSOR}", headers=h("admin"))
    assert response.status_code == 200 and response.json() == {"results": [], "next_cursor": None}


@pytest.mark.parametrize("cursor", MALFORMED_CURSORS.values(), ids=MALFORMED_CURSORS.keys())
async def test_malformed_cursor_is_rejected(client, people, cursor):
    response = await client.get(f"{BASE}/conversations?section=bot&cursor={cursor}", headers=h("agent"))
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_cursor" and response.json()["message"]


@pytest.mark.parametrize("section", ["bot", "test"])
async def test_cursor_from_another_org_only_positions_the_page(client, people, uow_factory, section):
    org_one, org_two = make_binding(org_id=1, graph_id=5), make_binding(org_id=2, graph_id=6)
    start, is_test = utcnow(), section == "test"
    await _seed(uow_factory, org_one, _spread(org_one, 60, start=start, is_test=is_test))
    # Org 2 rows on both sides of the cursor position: only the older ones may come back.
    newer = _spread(org_two, 5, start=start + timedelta(hours=1), is_test=is_test)
    older = _spread(org_two, 5, start=start - timedelta(hours=1), is_test=is_test)
    await _seed(uow_factory, org_two, newer + older)
    cursor = (await client.get(f"{BASE}/conversations?section={section}", headers=h("admin", org=1))).json()["next_cursor"]
    assert cursor is not None
    body = (await client.get(f"{BASE}/conversations?section={section}&cursor={cursor}", headers=h("admin", org=2))).json()
    assert [UUID(c["id"]) for c in body["results"]] == _bot_order(older)
    assert body["next_cursor"] is None


# ---- mode transitions keep handoff_at -----------------------------------------------------------

async def test_claiming_an_awaiting_conversation_keeps_its_place(client, people, uow_factory):
    binding = make_binding(org_id=1, graph_id=5)
    waiting = make_conversation(binding, mode="awaiting_human", handoff_at=utcnow() - timedelta(hours=2), last_message_at=utcnow())
    await _seed(uow_factory, binding, [waiting])
    claimed = await client.post(f"{BASE}/conversations/{waiting.id}/claim", json={}, headers=h("agent"))
    assert claimed.status_code == 200 and claimed.json()["mode"] == "human"
    async with uow_factory() as uow:
        assert (await uow.conversations.get(waiting.id)).handoff_at == waiting.handoff_at


async def _stored_handoff_at(uow_factory, conversation_id):
    async with uow_factory() as uow:
        return (await uow.conversations.get(UUID(conversation_id))).handoff_at


# ---- binding limits ----------------------------------------------------------------------------

async def test_limits_are_the_deployment_budgets_and_create_uses_the_defaults(client, people, settings):
    limits = await client.get(f"{BASE}/bindings/limits", headers=h("agent"))
    assert limits.status_code == 200, limits.text
    assert limits.json() == {
        "defaults": {
            "token_budget_per_conversation": settings.CHAT_CONVERSATION_TOKEN_BUDGET_DEFAULT, "daily_token_budget": settings.CHAT_DAILY_TOKEN_BUDGET_DEFAULT,
            "response_time_seconds": settings.CHAT_RESPONSE_TIME_DEFAULT, "close_after_seconds": settings.CHAT_CLOSE_AFTER_DEFAULT,
            "style": "support", "on_response_timeout": "handback", "handback_message": NEW_DESK_RULES["handback_message"],
        },
        "caps": {**_caps(settings), "response_time_seconds": settings.CHAT_RESPONSE_TIME_MAX, "close_after_seconds": settings.CHAT_CLOSE_AFTER_MAX},
    }
    # A body naming none of them gets every default the dialog was shown.
    created = (await client.post(f"{BASE}/bindings", json=NEW_BINDING, headers=h("admin"))).json()
    assert {name: created[name] for name in limits.json()["defaults"]} == limits.json()["defaults"]


async def test_limits_need_membership_and_chats_read(client, people):
    assert (await client.get(f"{BASE}/bindings/limits", headers=h("agent", org=2))).status_code == 404
    assert (await client.get(f"{BASE}/bindings/limits", headers=h("viewer"))).status_code == 403
    assert (await client.get(f"{BASE}/bindings/limits")).status_code == 401


async def test_claim_stands_when_stop_run_fails(client, people, monkeypatch):
    async def unreachable(session_id):
        raise UpstreamUnavailableError()

    monkeypatch.setattr(client.app.state.django, "stop_run", unreachable)
    binding = await _active_binding(client)
    test = (await client.post(f"{BASE}/bindings/{binding['id']}/test-conversation", headers=h("admin"))).json()
    visitor = {"Authorization": f"Bearer {test['visitor_token']}"}
    await client.post(f"/chat/public/v1/conversations/{test['conversation']['id']}/messages", json={"content": "help"}, headers=visitor)
    claimed = await client.post(f"{BASE}/conversations/{test['conversation']['id']}/claim", json={}, headers=h("agent"))
    assert claimed.status_code == 200 and claimed.json()["mode"] == "human"


async def test_every_save_rechecks_the_stored_flow(client, people, django):
    binding = await _active_binding(client)
    working = django.graphs[5]
    django.graphs[5] = django.graphs[7]  # the flow was broken in EpicStaff after the binding went live
    renamed = await client.patch(f"{BASE}/bindings/{binding['id']}", json={"name": "Renamed"}, headers=h("admin"))
    assert renamed.status_code == 200 and renamed.json()["name"] == "Renamed"
    assert renamed.json()["is_active"] is False and len(renamed.json()["contract_errors"]) == 3
    django.graphs[5] = working
    fixed = await client.patch(f"{BASE}/bindings/{binding['id']}", json={"name": "Fixed"}, headers=h("admin"))
    assert fixed.status_code == 200 and fixed.json()["contract_errors"] == []
    assert fixed.json()["is_active"] is False  # a save never resumes; resume does


async def test_saving_a_binding_whose_flow_was_deleted_marks_it_broken_and_pauses(client, people, django):
    binding = await _active_binding(client)
    django.graphs.pop(5)
    saved = await client.patch(f"{BASE}/bindings/{binding['id']}", json={"name": "Renamed"}, headers=h("admin"))
    assert saved.status_code == 200 and saved.json()["name"] == "Renamed"
    assert saved.json()["broken_reason"] == "The flow does not exist in this organization." and saved.json()["is_active"] is False


async def test_moving_a_binding_to_a_missing_flow_is_refused_and_stores_nothing(client, people):
    binding = await _active_binding(client)
    refused = await client.patch(f"{BASE}/bindings/{binding['id']}", json={"graph_id": 999, "name": "Moved"}, headers=h("admin"))
    assert (refused.status_code, refused.json()["code"]) == (400, "unknown_flow")
    stored = (await client.get(f"{BASE}/bindings/{binding['id']}", headers=h("admin"))).json()
    assert (stored["graph_id"], stored["name"], stored["is_active"]) == (5, "Support", True)


async def test_patch_with_the_same_flow_clears_fixed_contract_errors(client, people, django):
    binding = (await client.post(f"{BASE}/bindings", json={**NEW_BINDING, "graph_id": 7}, headers=h("admin"))).json()
    assert len(binding["contract_errors"]) == 3
    django.graphs[7] = CHAT_FLOW  # the flow was fixed in EpicStaff
    fixed = await client.patch(f"{BASE}/bindings/{binding['id']}", json={"graph_id": 7}, headers=h("admin"))
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["contract_errors"] == [] and fixed.json()["is_active"] is False


async def test_a_save_clears_the_broken_reason_of_a_live_binding(client, people, uow_factory):
    binding = await _active_binding(client)
    # The runtime marks a live binding broken when Django loses its flow (the 503 path).
    async with uow_factory() as uow:
        await uow.bindings.set_broken_reason(UUID(binding["id"]), "Django answered 404 for the flow.")
        await uow.commit()
    recovered = await client.patch(f"{BASE}/bindings/{binding['id']}", json={"name": "Renamed"}, headers=h("admin"))
    assert recovered.status_code == 200 and recovered.json()["broken_reason"] is None and recovered.json()["is_active"] is True


# ---- pause and resume -------------------------------------------------------------------------

async def test_pause_stops_the_widget_but_not_test_conversations(client, people):
    binding = await _active_binding(client)
    visitor_url, visitor = await _visitor(client, binding["public_key"])
    test = (await client.post(f"{BASE}/bindings/{binding['id']}/test-conversation", headers=h("admin"))).json()
    paused = await client.post(f"{BASE}/bindings/{binding['id']}/pause", headers=h("admin"))
    assert paused.status_code == 200 and paused.json()["is_active"] is False
    refused = await client.post(f"{visitor_url}/messages", json={"content": "hi"}, headers=visitor)
    assert (refused.status_code, refused.json()["code"]) == (410, "binding_inactive")
    sent = await client.post(f"/chat/public/v1/conversations/{test['conversation']['id']}/messages", json={"content": "hi"}, headers={"Authorization": f"Bearer {test['visitor_token']}"})
    assert sent.status_code == 202
    again = await client.post(f"{BASE}/bindings/{binding['id']}/pause", headers=h("admin"))
    assert again.status_code == 200 and again.json()["is_active"] is False


async def test_resume_with_a_clean_flow_activates_and_clears_the_broken_reason(client, people, uow_factory):
    binding = await _active_binding(client)
    await client.post(f"{BASE}/bindings/{binding['id']}/pause", headers=h("admin"))
    async with uow_factory() as uow:
        await uow.bindings.set_broken_reason(UUID(binding["id"]), "Django answered 404 for the flow.")
        await uow.commit()
    resumed = await client.post(f"{BASE}/bindings/{binding['id']}/resume", headers=h("admin"))
    assert resumed.status_code == 200, resumed.text
    assert (resumed.json()["is_active"], resumed.json()["broken_reason"], resumed.json()["contract_errors"]) == (True, None, [])
    again = await client.post(f"{BASE}/bindings/{binding['id']}/resume", headers=h("admin"))
    assert again.status_code == 200 and again.json()["is_active"] is True


async def test_resume_with_a_failing_flow_stores_fresh_errors_and_stays_paused(client, people, django):
    binding = await _active_binding(client)
    await client.post(f"{BASE}/bindings/{binding['id']}/pause", headers=h("admin"))
    django.graphs[5] = django.graphs[7]
    refused = await client.post(f"{BASE}/bindings/{binding['id']}/resume", headers=h("admin"))
    assert (refused.status_code, refused.json()["code"]) == (400, "contract_failed") and len(refused.json()["contract_errors"]) == 3
    stored = (await client.get(f"{BASE}/bindings/{binding['id']}", headers=h("admin"))).json()
    assert stored["is_active"] is False and stored["contract_errors"] == refused.json()["contract_errors"]


async def test_resume_with_a_deleted_flow_stores_the_broken_reason_and_stays_paused(client, people, django):
    binding = await _active_binding(client)
    await client.post(f"{BASE}/bindings/{binding['id']}/pause", headers=h("admin"))
    django.graphs.pop(5)
    refused = await client.post(f"{BASE}/bindings/{binding['id']}/resume", headers=h("admin"))
    assert (refused.status_code, refused.json()["code"]) == (400, "unknown_flow")
    stored = (await client.get(f"{BASE}/bindings/{binding['id']}", headers=h("admin"))).json()
    assert stored["is_active"] is False and stored["broken_reason"] == "The flow does not exist in this organization."


async def test_pause_and_resume_are_org_scoped_and_need_update(client, people, django):
    django.users["member"] = {"active": True, "user_id": 5, "email": "e@x", "scopes": [], "org_ids": [1], "is_superadmin": False}
    django.permissions[("member", 1)] = {"chats": ["read", "use"], "flows": ["read"]}
    foreign = (await client.post(f"{BASE}/bindings", json={**NEW_BINDING, "graph_id": 6}, headers=h("admin", org=2))).json()
    own = await _active_binding(client)
    for action in ("pause", "resume"):
        assert (await client.post(f"{BASE}/bindings/{foreign['id']}/{action}", headers=h("admin", org=1))).status_code == 404
        assert (await client.post(f"{BASE}/bindings/{own['id']}/{action}", headers=h("agent", org=2))).status_code == 404
        assert (await client.post(f"{BASE}/bindings/{own['id']}/{action}", headers=h("viewer"))).status_code == 403
        assert (await client.post(f"{BASE}/bindings/{own['id']}/{action}", headers=h("member"))).status_code == 403
    assert (await client.get(f"{BASE}/bindings/{foreign['id']}", headers=h("admin", org=2))).json()["is_active"] is True


async def test_saving_or_resuming_without_flows_read_is_forbidden_and_stores_nothing(client, people, django):
    binding = (await client.post(f"{BASE}/bindings", json={**NEW_BINDING, "graph_id": 7}, headers=h("admin"))).json()
    django.graphs.pop(7)  # a check that ran would now store a broken reason
    for refused in (
        await client.patch(f"{BASE}/bindings/{binding['id']}", json={"name": "Renamed"}, headers=h("binder")),
        await client.post(f"{BASE}/bindings/{binding['id']}/resume", headers=h("binder")),
    ):
        assert (refused.status_code, refused.json()["code"]) == (403, "flow_forbidden")
    stored = (await client.get(f"{BASE}/bindings/{binding['id']}", headers=h("admin"))).json()
    assert (stored["name"], stored["is_active"], stored["contract_errors"], stored["broken_reason"]) == ("Support", False, binding["contract_errors"], None)


# ---- contract read ------------------------------------------------------------------------------

async def test_contract_read_answers_the_flows_errors(client, people):
    passing = await client.get(f"{BASE}/bindings/contract?graph_id=5", headers=h("admin"))
    assert passing.status_code == 200 and passing.json() == {"contract_errors": []}
    failing = await client.get(f"{BASE}/bindings/contract?graph_id=7", headers=h("admin"))
    assert failing.status_code == 200 and len(failing.json()["contract_errors"]) == 3


@pytest.mark.parametrize("query", ["?graph_id=6", "?graph_id=999", "?graph_id=0", ""])
async def test_contract_read_refuses_another_orgs_missing_or_invalid_graph(client, people, query):
    refused = await client.get(f"{BASE}/bindings/contract{query}", headers=h("admin"))
    assert refused.status_code == 400


async def test_contract_read_of_another_orgs_graph_is_unknown_flow(client, people):
    refused = await client.get(f"{BASE}/bindings/contract?graph_id=6", headers=h("admin"))
    assert refused.json() == {"code": "unknown_flow", "message": "The flow does not exist in this organization."}


async def test_contract_read_needs_membership_and_chats_read(client, people, django):
    django.users["member"] = {"active": True, "user_id": 5, "email": "e@x", "scopes": [], "org_ids": [1], "is_superadmin": False}
    django.permissions[("member", 1)] = {"chats": ["read", "use"], "flows": ["read"]}
    assert (await client.get(f"{BASE}/bindings/contract?graph_id=5", headers=h("member"))).status_code == 200
    assert (await client.get(f"{BASE}/bindings/contract?graph_id=5", headers=h("agent", org=2))).status_code == 404
    assert (await client.get(f"{BASE}/bindings/contract?graph_id=5", headers=h("viewer"))).status_code == 403


# ---- display names ------------------------------------------------------------------------------

async def test_display_names_default_to_the_binding_name_and_support(client, people):
    long_name = "A" * 70
    created = (await client.post(f"{BASE}/bindings", json={**NEW_BINDING, "name": long_name}, headers=h("admin"))).json()
    assert (created["bot_display_name"], created["operator_display_name"]) == ("A" * 64, "Support")


@pytest.mark.parametrize("field", ["bot_display_name", "operator_display_name"])
@pytest.mark.parametrize("value", ["x" * 65, "   ", ""])
async def test_create_refuses_a_too_long_or_blank_display_name(client, people, field, value):
    refused = await client.post(f"{BASE}/bindings", json={**NEW_BINDING, field: value}, headers=h("admin"))
    assert (refused.status_code, refused.json()["code"]) == (400, "validation_error")
    assert (await client.get(f"{BASE}/bindings", headers=h("admin"))).json() == []


async def test_create_with_null_display_names_takes_the_defaults(client, people):
    created = await client.post(f"{BASE}/bindings", json={**NEW_BINDING, "bot_display_name": None, "operator_display_name": None}, headers=h("admin"))
    assert created.status_code == 201
    assert (created.json()["bot_display_name"], created.json()["operator_display_name"]) == ("Support", "Support")


async def test_the_binding_name_is_stripped_and_a_blank_one_refused(client, people):
    blank = await client.post(f"{BASE}/bindings", json={**NEW_BINDING, "name": "   "}, headers=h("admin"))
    assert (blank.status_code, blank.json()["code"]) == (400, "validation_error")
    created = (await client.post(f"{BASE}/bindings", json={**NEW_BINDING, "name": "  Sales  "}, headers=h("admin"))).json()
    assert (created["name"], created["bot_display_name"]) == ("Sales", "Sales")
    blank_patch = await client.patch(f"{BASE}/bindings/{created['id']}", json={"name": "   "}, headers=h("admin"))
    assert blank_patch.status_code == 400
    renamed = await client.patch(f"{BASE}/bindings/{created['id']}", json={"name": " Billing "}, headers=h("admin"))
    assert renamed.json()["name"] == "Billing"


async def test_patch_persists_display_names_and_refuses_null(client, people):
    binding = await _active_binding(client)
    for field in ("bot_display_name", "operator_display_name"):
        refused = await client.patch(f"{BASE}/bindings/{binding['id']}", json={field: None}, headers=h("admin"))
        assert refused.status_code == 400
    saved = await client.patch(f"{BASE}/bindings/{binding['id']}", json={"bot_display_name": " Ava ", "operator_display_name": "Team"}, headers=h("admin"))
    assert saved.status_code == 200
    stored = (await client.get(f"{BASE}/bindings/{binding['id']}", headers=h("admin"))).json()
    assert (stored["bot_display_name"], stored["operator_display_name"]) == ("Ava", "Team")


BUDGETS = ("token_budget_per_conversation", "daily_token_budget")


def _caps(settings) -> dict[str, int]:
    return {"token_budget_per_conversation": settings.CHAT_CONVERSATION_TOKEN_BUDGET_MAX, "daily_token_budget": settings.CHAT_DAILY_TOKEN_BUDGET_MAX}


@pytest.mark.parametrize("name", BUDGETS)
async def test_create_accepts_a_budget_at_the_cap_and_rejects_one_above(client, people, settings, name):
    cap = _caps(settings)[name]
    at_cap = await client.post(f"{BASE}/bindings", json={**NEW_BINDING, name: cap}, headers=h("admin"))
    assert at_cap.status_code == 201 and at_cap.json()[name] == cap
    above = await client.post(f"{BASE}/bindings", json={**NEW_BINDING, name: cap + 1}, headers=h("admin"))
    assert above.status_code == 400
    assert above.json() == {"code": "budget_above_cap", "message": f"`{name}` cannot exceed {cap} on this deployment.", "field": name, "max": cap}
    assert len((await client.get(f"{BASE}/bindings", headers=h("admin"))).json()) == 1


@pytest.mark.parametrize("name", BUDGETS)
@pytest.mark.parametrize("value", [None, 0])
async def test_create_rejects_a_null_or_zero_budget(client, people, name, value):
    refused = await client.post(f"{BASE}/bindings", json={**NEW_BINDING, name: value}, headers=h("admin"))
    assert (refused.status_code, refused.json()["code"]) == (400, "validation_error")


@pytest.mark.parametrize("name", BUDGETS)
async def test_patch_rejects_a_null_budget_and_keeps_the_stored_one(client, people, name):
    binding = (await client.post(f"{BASE}/bindings", json={**NEW_BINDING, name: 500}, headers=h("admin"))).json()
    refused = await client.patch(f"{BASE}/bindings/{binding['id']}", json={name: None}, headers=h("admin"))
    assert (refused.status_code, refused.json()["code"]) == (400, "validation_error") and name in refused.json()["message"]
    assert (await client.get(f"{BASE}/bindings/{binding['id']}", headers=h("admin"))).json()[name] == 500


@pytest.mark.parametrize("name", BUDGETS)
async def test_patch_above_the_cap_is_rejected_and_stores_nothing(client, people, settings, name):
    cap = _caps(settings)[name]
    binding = (await client.post(f"{BASE}/bindings", json={**NEW_BINDING, name: 500}, headers=h("admin"))).json()
    above = await client.patch(f"{BASE}/bindings/{binding['id']}", json={"name": "Renamed", name: cap + 1}, headers=h("admin"))
    assert (above.status_code, above.json()["code"], above.json()["max"]) == (400, "budget_above_cap", cap)
    stored = (await client.get(f"{BASE}/bindings/{binding['id']}", headers=h("admin"))).json()
    assert (stored[name], stored["name"]) == (500, "Support")
    at_cap = await client.patch(f"{BASE}/bindings/{binding['id']}", json={name: cap}, headers=h("admin"))
    assert at_cap.status_code == 200 and at_cap.json()[name] == cap


async def test_patch_omitting_budgets_keeps_them(client, people):
    binding = (await client.post(f"{BASE}/bindings", json={**NEW_BINDING, "token_budget_per_conversation": 500, "daily_token_budget": 7000}, headers=h("admin"))).json()
    renamed = await client.patch(f"{BASE}/bindings/{binding['id']}", json={"name": "Renamed"}, headers=h("admin"))
    assert renamed.status_code == 200
    body = renamed.json()
    assert (body["name"], body["token_budget_per_conversation"], body["daily_token_budget"]) == ("Renamed", 500, 7000)


async def test_patch_null_is_refused_for_other_fields_too(client, people):
    binding = (await client.post(f"{BASE}/bindings", json=NEW_BINDING, headers=h("admin"))).json()
    refused = await client.patch(f"{BASE}/bindings/{binding['id']}", json={"name": None}, headers=h("admin"))
    assert refused.status_code == 400


async def test_release_in_bot_mode_emits_nothing(client, people, uow_factory):
    binding = await _active_binding(client)
    test = (await client.post(f"{BASE}/bindings/{binding['id']}/test-conversation", headers=h("admin"))).json()
    released = await client.post(f"{BASE}/conversations/{test['conversation']['id']}/release", headers=h("agent"))
    assert released.status_code == 200 and released.json()["mode"] == "bot"
    async with uow_factory() as uow:
        events = await uow.events.replay(Stream.CONVERSATION, conversation_id=UUID(test["conversation"]["id"]), after_seq=None)
    assert events == []


ROUTES = [
    ("get", "/bindings/{binding}", None),
    ("patch", "/bindings/{binding}", {"name": "x"}),
    ("delete", "/bindings/{binding}", None),
    ("post", "/bindings/{binding}/rotate-key", None),
    ("post", "/bindings/{binding}/pause", None),
    ("post", "/bindings/{binding}/resume", None),
    ("get", "/bindings/{binding}/snippet", None),
    ("post", "/bindings/{binding}/test-conversation", None),
    ("post", "/conversations/{conversation}/visitor-token", None),
    ("get", "/conversations?section=human", None),
    ("get", "/conversations?section=waiting&mine=true&q=1", None),
    ("get", "/inbox/badges", None),
    ("get", "/bindings/my-aliases", None),
    ("put", "/bindings/{binding}/my-alias", {"alias": "Mike"}),
    ("get", "/conversations/{conversation}", None),
    ("get", "/conversations/{conversation}/messages", None),
    ("post", "/conversations/{conversation}/claim", {}),
    ("post", "/conversations/{conversation}/close", {}),
    ("post", "/conversations/{conversation}/release", None),
    ("post", "/conversations/{conversation}/messages", {"content": "hi"}),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
async def test_every_route_hides_other_orgs_and_needs_permission(client, people, method, path, body):
    binding = await _active_binding(client)
    test = (await client.post(f"{BASE}/bindings/{binding['id']}/test-conversation", headers=h("admin"))).json()
    url = BASE + path.format(binding=binding["id"], conversation=test["conversation"]["id"])
    kwargs = {"json": body} if body is not None else {}
    other_org = await getattr(client, method)(url, headers=h("admin", org=2), **kwargs)
    # The conversation list and the badges have no id to hide: they answer empty for the other org.
    expected = 200 if path.startswith(("/conversations?", "/inbox/badges", "/bindings/my-aliases")) else 404
    assert other_org.status_code == expected, other_org.text
    assert (await getattr(client, method)(url, headers=h("viewer"), **kwargs)).status_code == 403


# ---- action replies in the operator view -------------------------------------------------------

async def test_operators_see_action_replies_but_not_extra_data_and_other_orgs_see_nothing(client, people, uow_factory):
    binding = await _active_binding(client)
    test = (await client.post(f"{BASE}/bindings/{binding['id']}/test-conversation", headers=h("admin"))).json()
    conversation_id, visitor = test["conversation"]["id"], {"Authorization": f"Bearer {test['visitor_token']}"}
    action = {"type": "button", "id": "refund"}
    body = {"action": action, "chat_extra_data": {"secret_context": "visitor-only"}}
    assert (await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json=body, headers=visitor)).status_code == 202

    (message,) = (await client.get(f"{BASE}/conversations/{conversation_id}/messages", headers=h("agent"))).json()
    assert (message["role"], message["content"], message["action"]) == ("user", "", action)
    async with uow_factory() as uow:
        inbox = await uow.events.replay(Stream.INBOX, org_id=1, after_seq=None)
    created = [e.payload for e in inbox if e.type == "message.created"]
    assert [payload["action"] for payload in created] == [action]
    (item,) = (await client.get(f"{BASE}/conversations?section=test", headers=h("admin"))).json()["results"]
    assert item["last_message_preview"] == '{"type":"button","id":"refund"}'
    assert "visitor-only" not in str([e.payload for e in inbox]) and "chat_extra_data" not in item

    assert (await client.get(f"{BASE}/conversations/{conversation_id}/messages", headers=h("admin", org=2))).status_code == 404
    async with uow_factory() as uow:
        assert await uow.events.replay(Stream.INBOX, org_id=2, after_seq=None) == []


async def test_an_operator_reply_with_nul_is_400_and_stores_nothing(client, people):
    binding = await _active_binding(client)
    test = (await client.post(f"{BASE}/bindings/{binding['id']}/test-conversation", headers=h("admin"))).json()
    conversation_id = test["conversation"]["id"]
    assert (await client.post(f"{BASE}/conversations/{conversation_id}/claim", json={}, headers=h("agent"))).status_code == 200
    refused = await client.post(f"{BASE}/conversations/{conversation_id}/messages", json={"content": "hi\x00"}, headers=h("agent"))
    assert (refused.status_code, refused.json()["code"]) == (400, "validation_error")
    assert (await client.get(f"{BASE}/conversations/{conversation_id}/messages", headers=h("agent"))).json() == []


# ---- a fresh visitor token for an existing test conversation ------------------------------------

async def test_a_test_conversation_gets_a_new_visitor_token_that_works_only_for_it(client, people):
    binding = await _active_binding(client)
    first = (await client.post(f"{BASE}/bindings/{binding['id']}/test-conversation", headers=h("admin"))).json()
    second = (await client.post(f"{BASE}/bindings/{binding['id']}/test-conversation", headers=h("admin"))).json()
    conversation_id = first["conversation"]["id"]
    minted = await client.post(f"{BASE}/conversations/{conversation_id}/visitor-token", headers=h("admin"))
    assert minted.status_code == 201 and set(minted.json()) == {"visitor_token"}
    token = minted.json()["visitor_token"]
    assert token != first["visitor_token"]
    visitor = {"Authorization": f"Bearer {token}"}
    public = "/chat/public/v1/conversations"
    assert (await client.get(f"{public}/{conversation_id}", headers=visitor)).status_code == 200
    sent = await client.post(f"{public}/{conversation_id}/messages", json={"content": "hello again"}, headers=visitor)
    assert sent.status_code == 202
    foreign = await client.get(f"{public}/{second['conversation']['id']}", headers=visitor)
    assert (foreign.status_code, foreign.json()["code"]) == (404, "not_found")
    # The token the operator already held keeps working.
    assert (await client.get(f"{public}/{conversation_id}", headers={"Authorization": f"Bearer {first['visitor_token']}"})).status_code == 200


async def test_a_real_visitors_conversation_never_gets_a_token(client, people, session_factory):
    binding = await _active_binding(client)
    created = (await client.post("/chat/public/v1/conversations", json={"public_key": binding["public_key"]}, headers={"Origin": ORIGIN})).json()
    refused = await client.post(f"{BASE}/conversations/{created['conversation_id']}/visitor-token", headers=h("admin"))
    assert (refused.status_code, refused.json()["code"]) == (400, "not_a_test_conversation")
    async with session_factory() as session:
        tokens = await session.scalar(select(func.count()).select_from(VisitorTokenRow).where(VisitorTokenRow.conversation_id == UUID(created["conversation_id"])))
    assert tokens == 1  # only the visitor's own


async def test_minting_a_visitor_token_needs_authentication(client, people):
    binding = await _active_binding(client)
    test = (await client.post(f"{BASE}/bindings/{binding['id']}/test-conversation", headers=h("admin"))).json()
    response = await client.post(f"{BASE}/conversations/{test['conversation']['id']}/visitor-token")
    assert response.status_code == 401


# ---- visitor numbers, the visitor's wait and operator names on the inbox row ---------------------

ROW_FIELDS = {"visitor_number", "visitor_waiting_since", "last_message_role", "last_message_author_user_id", "last_message_author_name", "assigned_operator_name", "chat_user_id"}


async def _inbox(uow_factory, conversation_id, event_type):
    async with uow_factory() as uow:
        events = await uow.events.replay(Stream.INBOX, org_id=1, after_seq=None)
    return [e.payload for e in events if e.type == event_type and e.conversation_id == conversation_id]


async def _listed(client, section, conversation_id, user="agent"):
    rows = (await client.get(f"{BASE}/conversations?section={section}", headers=h(user))).json()["results"]
    return next(row for row in rows if row["id"] == str(conversation_id))


async def test_the_row_fields_round_trip_on_the_list_the_take_over_and_conversation_updated(client, people, django, uow_factory):
    django.users["agent"]["display_name"] = "Bea Agent"
    django.users["admin"]["display_name"] = "Ada Admin"
    binding = make_binding(org_id=1, graph_id=5)
    handed_off_at = utcnow() - timedelta(minutes=10)
    waiting = make_conversation(binding, subject="customer-42", is_signed=True, mode="awaiting_human", handoff_at=handed_off_at, visitor_waiting_since=handed_off_at, last_message_at=handed_off_at, last_message_role=Role.USER)
    await _seed(uow_factory, binding, [waiting])

    listed = await _listed(client, "human", waiting.id)
    assert ROW_FIELDS <= listed.keys() and set(listed) == set(ConversationOutput.model_fields)
    assert (listed["visitor_number"], listed["chat_user_id"], listed["last_message_role"]) == (waiting.visitor_number, "customer-42", "user")
    assert datetime.fromisoformat(listed["visitor_waiting_since"]) == handed_off_at
    assert (listed["assigned_operator_name"], listed["last_message_author_user_id"], listed["last_message_author_name"]) == (None, None, None)

    claimed = (await client.post(f"{BASE}/conversations/{waiting.id}/claim", json={}, headers=h("agent"))).json()
    assert (claimed["assigned_operator_id"], claimed["assigned_operator_name"]) == (2, "Bea Agent")
    assert datetime.fromisoformat(claimed["visitor_waiting_since"]) == handed_off_at  # taking over is not answering
    assert claimed == await _listed(client, "human", waiting.id)
    assert ConversationOutput.model_validate((await _inbox(uow_factory, waiting.id, "conversation.updated"))[-1]).model_dump(mode="json") == claimed

    reply = (await client.post(f"{BASE}/conversations/{waiting.id}/messages", json={"content": "Hi, Bea here"}, headers=h("agent"))).json()
    assert (reply["author_user_id"], reply["author_name"]) == (2, "Bea Agent")
    answered = await _listed(client, "human", waiting.id)
    assert answered["visitor_waiting_since"] is None
    assert (answered["last_message_role"], answered["last_message_author_user_id"], answered["last_message_author_name"]) == ("operator", 2, "Bea Agent")
    (created,) = await _inbox(uow_factory, waiting.id, "message.created")
    assert (created["author_user_id"], created["author_name"], created["id"]) == (2, "Bea Agent", reply["id"])

    # Two operators on one row: the new holder and the previous holder who wrote last.
    forced = (await client.post(f"{BASE}/conversations/{waiting.id}/claim", json={"force": True}, headers=h("admin"))).json()
    assert (forced["assigned_operator_name"], forced["last_message_author_name"]) == ("Ada Admin", "Bea Agent")
    updated = (await _inbox(uow_factory, waiting.id, "conversation.updated"))[-1]
    assert ConversationOutput.model_validate(updated).model_dump(mode="json") == forced == await _listed(client, "human", waiting.id)
    page = (await client.get(f"{BASE}/conversations/{waiting.id}/messages", headers=h("admin"))).json()
    assert [(m["role"], m["author_user_id"], m["author_name"]) for m in page] == [("operator", 2, "Bea Agent")]

    released = (await client.post(f"{BASE}/conversations/{waiting.id}/release", headers=h("admin"))).json()
    assert (released["assigned_operator_name"], released["visitor_waiting_since"], released["last_message_author_name"]) == (None, None, "Bea Agent")
    assert ConversationOutput.model_validate((await _inbox(uow_factory, waiting.id, "conversation.updated"))[-1]).model_dump(mode="json") == released


async def test_a_test_conversation_row_is_numbered_on_the_desks_sequence_and_names_nobody(client, people, uow_factory):
    binding = await _active_binding(client)
    _, visitor = await _visitor(client, binding["public_key"])
    test = (await client.post(f"{BASE}/bindings/{binding['id']}/test-conversation", headers=h("admin"))).json()["conversation"]
    assert set(test) == set(ConversationOutput.model_fields)
    assert (test["visitor_number"], test["chat_user_id"], test["visitor_waiting_since"], test["last_message_role"], test["assigned_operator_name"]) == (2, None, None, None, None)
    (announced,) = await _inbox(uow_factory, UUID(test["id"]), "conversation.updated")
    assert ConversationOutput.model_validate(announced).model_dump(mode="json") == test


async def test_names_are_null_when_epicstaff_sends_none(client, people, django, uow_factory, session_factory):
    django.introspect_omits_display_name = True
    binding = await _active_binding(client)
    conversation_id = (await client.post(f"{BASE}/bindings/{binding['id']}/test-conversation", headers=h("admin"))).json()["conversation"]["id"]
    claimed = (await client.post(f"{BASE}/conversations/{conversation_id}/claim", json={}, headers=h("agent"))).json()
    assert (claimed["assigned_operator_id"], claimed["assigned_operator_name"]) == (2, None)
    reply = (await client.post(f"{BASE}/conversations/{conversation_id}/messages", json={"content": "hi"}, headers=h("agent"))).json()
    assert (reply["author_user_id"], reply["author_name"]) == (2, None)
    row = await _listed(client, "test", conversation_id, user="admin")
    assert (row["assigned_operator_name"], row["last_message_author_user_id"], row["last_message_author_name"]) == (None, 2, None)
    (message,) = (await client.get(f"{BASE}/conversations/{conversation_id}/messages", headers=h("agent"))).json()
    assert message["author_name"] is None
    (created,) = await _inbox(uow_factory, UUID(conversation_id), "message.created")
    assert (created["author_user_id"], created["author_name"]) == (2, None)
    assert {(u["assigned_operator_name"], u["last_message_author_name"]) for u in await _inbox(uow_factory, UUID(conversation_id), "conversation.updated")} == {(None, None)}
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(OperatorProfileRow)) == 0


async def test_another_orgs_list_shows_none_of_the_rows_or_their_names(client, people, django, uow_factory):
    django.users["agent"]["display_name"] = "Bea Agent"
    binding = await _active_binding(client)
    conversation_id = (await client.post(f"{BASE}/bindings/{binding['id']}/test-conversation", headers=h("admin"))).json()["conversation"]["id"]
    await client.post(f"{BASE}/conversations/{conversation_id}/claim", json={}, headers=h("agent"))
    await client.post(f"{BASE}/conversations/{conversation_id}/messages", json={"content": "hi"}, headers=h("agent"))
    other_org = await client.get(f"{BASE}/conversations?section=test", headers=h("admin", org=2))
    assert other_org.json() == {"results": [], "next_cursor": None} and "Bea Agent" not in other_org.text
    assert (await client.get(f"{BASE}/conversations/{conversation_id}/messages", headers=h("admin", org=2))).status_code == 404
    async with uow_factory() as uow:
        assert await uow.events.replay(Stream.INBOX, org_id=2, after_seq=None) == []


# ---- sections waiting, in progress, bot and test; order, mine, search, badges -------------------

SECTIONS = ("waiting", "in_progress", "bot", "test", "closed")


async def _sections_listing(client, conversation_id, user="admin"):
    found = []
    for section in SECTIONS:
        ids, _ = await _walk(client, f"section={section}", headers=h(user))
        if conversation_id in ids:
            found.append(section)
    return found


async def _with_visitor_token(uow_factory, conversation):
    token, token_hash = issue_visitor_token()
    async with uow_factory() as uow:
        await uow.visitor_tokens.add(VisitorToken(token_hash, conversation.id, utcnow(), utcnow()))
        await uow.commit()
    return {"Authorization": f"Bearer {token}", "Origin": ORIGIN}


async def _name(uow_factory, user_id, display_name, org_id=1):
    async with uow_factory() as uow:
        await uow.operator_profiles.remember(org_id, user_id, display_name, utcnow())
        await uow.commit()


def _held(binding, holder, at, *, waiting=False, **overrides):
    """A taken conversation: in progress, or waiting when the visitor wrote after the last reply."""
    return make_conversation(binding, mode="human", assigned_operator_id=holder, last_message_at=at, visitor_waiting_since=at if waiting else None, **overrides)


async def test_a_conversation_moves_between_sections_and_is_never_in_two(client, people, uow_factory):
    binding = make_binding(org_id=1, graph_id=5)
    handed_off_at = utcnow() - timedelta(minutes=5)
    conversation = make_conversation(binding, mode="awaiting_human", handoff_at=handed_off_at, visitor_waiting_since=handed_off_at, last_message_at=handed_off_at)
    await _seed(uow_factory, binding, [conversation])
    visitor = await _with_visitor_token(uow_factory, conversation)
    public = f"/chat/public/v1/conversations/{conversation.id}/messages"
    assert await _sections_listing(client, conversation.id) == ["waiting"]
    assert (await client.post(f"{BASE}/conversations/{conversation.id}/claim", json={}, headers=h("agent"))).status_code == 200
    assert await _sections_listing(client, conversation.id) == ["waiting"]  # taking over is not answering
    assert (await client.post(f"{BASE}/conversations/{conversation.id}/messages", json={"content": "Hi"}, headers=h("agent"))).status_code == 201
    assert await _sections_listing(client, conversation.id) == ["in_progress"]
    assert (await client.post(public, json={"content": "one more thing"}, headers=visitor)).json()["state"] == "forwarded_to_operator"
    assert await _sections_listing(client, conversation.id) == ["waiting"]
    await client.post(f"{BASE}/conversations/{conversation.id}/messages", json={"content": "Sure"}, headers=h("agent"))
    assert await _sections_listing(client, conversation.id) == ["in_progress"]
    assert (await client.post(f"{BASE}/conversations/{conversation.id}/release", headers=h("agent"))).status_code == 200
    assert await _sections_listing(client, conversation.id) == ["bot"]


async def test_a_visitor_taken_over_before_the_bot_answered_waits_until_an_operator_replies(client, people, uow_factory):
    binding = await _active_binding(client)
    url, visitor = await _visitor(client, binding["public_key"])
    conversation_id = UUID(url.rsplit("/", 1)[1])
    assert (await client.post(f"{url}/messages", json={"content": "help"}, headers=visitor)).json()["state"] == "processing"
    assert await _sections_listing(client, conversation_id) == ["bot"]  # the bot's run is in flight
    claimed = (await client.post(f"{BASE}/conversations/{conversation_id}/claim", json={}, headers=h("agent"))).json()
    assert claimed["visitor_waiting_since"] == claimed["last_message_at"] is not None
    assert await _sections_listing(client, conversation_id) == ["waiting"]
    badges = (await client.get(f"{BASE}/inbox/badges", headers=h("agent"))).json()["waiting"]
    assert [(b["id"], b["assigned_operator_id"]) for b in badges] == [(str(conversation_id), 2)]
    await client.post(f"{BASE}/conversations/{conversation_id}/messages", json={"content": "Hi"}, headers=h("agent"))
    assert await _sections_listing(client, conversation_id) == ["in_progress"]
    assert (await client.get(f"{BASE}/inbox/badges", headers=h("agent"))).json() == {"waiting": []}


async def test_every_state_lands_in_exactly_one_section(client, people, uow_factory):
    binding, now = make_binding(org_id=1, graph_id=5), utcnow()
    rows = {
        "bot": make_conversation(binding, last_message_at=now),
        "waiting": make_conversation(binding, mode="awaiting_human", last_message_at=now),
        "waiting before saying anything": make_conversation(binding, mode="awaiting_human"),
        "held, visitor wrote again": _held(binding, 2, now, waiting=True),
        "held and answered": _held(binding, 2, now),
        "test, waiting": make_conversation(binding, mode="awaiting_human", is_test=True, last_message_at=now),
        "test, held": _held(binding, 2, now, is_test=True),
        "closed from the bot": make_closed(binding, last_message_at=now),
        "closed while waiting": make_closed(binding, mode="awaiting_human", last_message_at=now),
        "resolved while held": make_closed(binding, reason="resolved", mode="human", assigned_operator_id=2, last_message_at=now),
        "closed test": make_closed(binding, is_test=True, last_message_at=now),
        "closed before saying anything": make_closed(binding),
    }
    await _seed(uow_factory, binding, list(rows.values()))
    expected = {
        "bot": ["bot"], "waiting": ["waiting"], "waiting before saying anything": ["waiting"], "held, visitor wrote again": ["waiting"],
        "held and answered": ["in_progress"], "test, waiting": ["test"], "test, held": ["test"], "closed from the bot": ["closed"],
        "closed while waiting": ["closed"], "resolved while held": ["closed"], "closed test": ["test"], "closed before saying anything": [],
    }
    for name, conversation in rows.items():
        assert await _sections_listing(client, conversation.id) == expected[name], name
    # Human, kept for older clients, lists open hand-offs only.
    human, _ = await _walk(client, "section=human")
    assert set(human) == {rows[name].id for name in ("waiting", "waiting before saying anything", "held, visitor wrote again", "held and answered")}


async def test_waiting_is_longest_wait_first_whatever_the_order(client, people, uow_factory):
    binding, start = make_binding(org_id=1, graph_id=5), utcnow() - timedelta(hours=1)
    # Threes share a wait start, so the page boundary (50) splits one; activity runs the other
    # way, so an activity order cannot pass.
    rows = [
        make_conversation(binding, mode="awaiting_human", visitor_waiting_since=start + timedelta(seconds=index // 3), last_message_at=start - timedelta(seconds=index))
        for index in range(PAGE_SIZE + 5)
    ]
    await _seed(uow_factory, binding, rows)
    expected = [c.id for c in sorted(rows, key=lambda c: (c.visitor_waiting_since, c.id))]
    for query in ("section=waiting", "section=waiting&order=newest", "section=waiting&order=oldest"):
        ids, sizes = await _walk(client, query)
        assert (ids, sizes) == (expected, [PAGE_SIZE, 5]), query
    listed = (await client.get(f"{BASE}/conversations?section=waiting", headers=h("agent"))).json()["results"][0]
    assert datetime.fromisoformat(listed["visitor_waiting_since"]) == rows[0].visitor_waiting_since


@pytest.mark.parametrize("section", ["in_progress", "bot", "test"])
async def test_newest_and_oldest_walk_the_same_rows_in_opposite_orders_across_pages(client, people, uow_factory, section):
    """55 rows in groups of three sharing a timestamp: newest first splits rows 48-50 at the
    page boundary, oldest first splits rows 3-5, so the id tiebreak is crossed both ways."""
    binding, start = make_binding(org_id=1, graph_id=5), utcnow()
    if section == "in_progress":
        rows = [_held(binding, 2, start - timedelta(seconds=index // 3)) for index in range(PAGE_SIZE + 5)]
    else:
        rows = _spread(binding, PAGE_SIZE + 5, start=start, group=3, is_test=section == "test")
    await _seed(uow_factory, binding, rows)
    headers = h("admin")
    newest, newest_sizes = await _walk(client, f"section={section}&order=newest", headers)
    oldest, oldest_sizes = await _walk(client, f"section={section}&order=oldest", headers)
    assert newest == _bot_order(rows) and oldest == newest[::-1]
    assert newest_sizes == oldest_sizes == [PAGE_SIZE, 5]
    assert (await _walk(client, f"section={section}", headers))[0] == newest  # newest first unless asked


async def test_mine_lists_only_the_callers_conversations(client, people, uow_factory):
    binding, now = make_binding(org_id=1, graph_id=5), utcnow()
    mine = {"waiting": _held(binding, 2, now, waiting=True), "in_progress": _held(binding, 2, now), "test": _held(binding, 2, now, is_test=True)}
    others = [_held(binding, 1, now, waiting=True), _held(binding, 1, now), make_conversation(binding, mode="awaiting_human", last_message_at=now), make_conversation(binding, last_message_at=now)]
    await _seed(uow_factory, binding, [*mine.values(), *others])
    for section, conversation in mine.items():
        if section == "test":  # read + use lists no tests, not even one it holds
            assert (await client.get(f"{BASE}/conversations?section=test&mine=true", headers=h("agent"))).status_code == 403
            assert (await _walk(client, "section=test&mine=true", headers=h("admin")))[0] == []
            continue
        assert (await _walk(client, f"section={section}&mine=true"))[0] == [conversation.id], section
        assert (await _walk(client, f"section={section}&mine=true", headers=h("admin")))[0] == [others[0 if section == "waiting" else 1].id], section
    assert (await _walk(client, "section=bot&mine=true"))[0] == []
    # Mine is the caller, never an id the client names.
    assert (await client.get(f"{BASE}/conversations?section=waiting&mine=1", headers=h("agent"))).status_code == 200
    assert (await client.get(f"{BASE}/conversations?section=waiting&mine=2", headers=h("agent"))).status_code == 400


async def test_search_matches_a_visitor_number_exactly_on_each_desk(client, people, uow_factory):
    desk, other_desk, now = make_binding(org_id=1, graph_id=5), make_binding(org_id=1, graph_id=5), utcnow()
    numbered = {(binding.id, number): make_conversation(binding, visitor_number=number, last_message_at=now) for binding in (desk, other_desk) for number in (2, 12, 22)}
    await _seed(uow_factory, desk, [c for (binding_id, _), c in numbered.items() if binding_id == desk.id])
    await _seed(uow_factory, other_desk, [c for (binding_id, _), c in numbered.items() if binding_id == other_desk.id])
    both_twos = {numbered[(desk.id, 2)].id, numbered[(other_desk.id, 2)].id}
    for q in ("2", "%232", "visitor%202", "Visitor%20%232", "VISITOR2"):
        assert set((await _walk(client, f"section=bot&q={q}"))[0]) == both_twos, q
    assert (await _walk(client, f"section=bot&q=2&binding={desk.id}"))[0] == [numbered[(desk.id, 2)].id]
    assert set((await _walk(client, "section=bot&q=12"))[0]) == {numbered[(desk.id, 12)].id, numbered[(other_desk.id, 12)].id}
    assert (await _walk(client, "section=bot&q=3"))[0] == []


async def test_search_matches_a_signed_visitors_id_by_prefix_and_never_an_anonymous_subject(client, people, uow_factory):
    binding, now = make_binding(org_id=1, graph_id=5), utcnow()
    signed = make_conversation(binding, subject="Customer-42", is_signed=True, last_message_at=now)
    other_signed = make_conversation(binding, subject="customer-7", is_signed=True, last_message_at=now - timedelta(seconds=1))
    # An anonymous subject is a random token: even one that happens to start the same never matches.
    anonymous = make_conversation(binding, subject="customer-42-random-token", last_message_at=now)
    underscore, letter = (make_conversation(binding, subject=subject, is_signed=True, last_message_at=now) for subject in ("a_b", "axb"))
    await _seed(uow_factory, binding, [signed, other_signed, anonymous, underscore, letter])
    assert (await _walk(client, "section=bot&q=CUSTOMER-4"))[0] == [signed.id]
    assert (await _walk(client, "section=bot&q=customer"))[0] == [signed.id, other_signed.id]
    assert (await _walk(client, "section=bot&q=customer-42-random"))[0] == []
    assert (await _walk(client, "section=bot&q=omer-42"))[0] == []  # a prefix, not a substring
    assert (await _walk(client, "section=bot&q=a_b"))[0] == [underscore.id]  # `_` is a character, not a wildcard


async def test_search_matches_the_holders_name_anywhere_in_it(client, people, uow_factory):
    binding, now = make_binding(org_id=1, graph_id=5), utcnow()
    bea_answered, bea_waiting = _held(binding, 2, now), _held(binding, 2, now, waiting=True)
    ada_answered = _held(binding, 1, now)
    percent, five_hundred = _held(binding, 7, now), _held(binding, 8, now)
    unheld = make_conversation(binding, mode="awaiting_human", last_message_at=now)
    await _seed(uow_factory, binding, [bea_answered, bea_waiting, ada_answered, percent, five_hundred, unheld])
    for user_id, name in ((2, "Bea Agent"), (1, "Ada Admin"), (7, "50% Off"), (8, "500 Off")):
        await _name(uow_factory, user_id, name)
    assert (await _walk(client, "section=in_progress&q=AGENT"))[0] == [bea_answered.id]
    assert (await _walk(client, "section=waiting&q=agent"))[0] == [bea_waiting.id]
    assert (await _walk(client, "section=in_progress&q=a%20ag"))[0] == [bea_answered.id]
    assert (await _walk(client, "section=in_progress&q=admin"))[0] == [ada_answered.id]
    assert (await _walk(client, "section=in_progress&q=50%25"))[0] == [percent.id]  # `%` is a character, not a wildcard
    assert (await _walk(client, "section=bot&q=agent"))[0] == []


async def test_search_lowers_both_sides_the_same_way(client, people, uow_factory):
    """Python lowers "İ" to "i" plus a combining dot and a final "Σ" to "ς"; Postgres lowers them
    to "i" and "σ". Both sides go through Postgres, so what is typed matches what is stored."""
    binding, now = make_binding(org_id=1, graph_id=5), utcnow()
    ipek, odos = _held(binding, 7, now), _held(binding, 8, now)
    signed = make_conversation(binding, subject="İD-42", is_signed=True, last_message_at=now)
    await _seed(uow_factory, binding, [ipek, odos, signed])
    await _name(uow_factory, 7, "İpek Agent")
    await _name(uow_factory, 8, "ΟΔΟΣ Team")
    assert (await _walk(client, "section=in_progress&q=İPEK"))[0] == [ipek.id]
    assert (await _walk(client, "section=in_progress&q=ipek"))[0] == [ipek.id]
    assert (await _walk(client, "section=in_progress&q=ΟΔΟΣ"))[0] == [odos.id]
    assert (await _walk(client, "section=bot&q=İD-4"))[0] == [signed.id]


async def test_search_composes_with_mine_order_and_paging(client, people, uow_factory):
    binding, start = make_binding(org_id=1, graph_id=5), utcnow()
    beas = [_held(binding, 2, start - timedelta(seconds=index)) for index in range(PAGE_SIZE + 5)]
    adas = [_held(binding, 1, start - timedelta(seconds=index, milliseconds=500)) for index in range(10)]
    await _seed(uow_factory, binding, [*beas, *adas])
    await _name(uow_factory, 2, "Bea Agent")
    await _name(uow_factory, 1, "Ada Admin")
    newest, sizes = await _walk(client, "section=in_progress&q=agent")
    assert newest == _bot_order(beas) and sizes == [PAGE_SIZE, 5]
    assert (await _walk(client, "section=in_progress&q=agent&order=oldest"))[0] == newest[::-1]
    assert (await _walk(client, "section=in_progress&q=agent&mine=true"))[0] == newest
    assert (await _walk(client, "section=in_progress&q=agent&mine=true", headers=h("admin")))[0] == []
    assert (await _walk(client, "section=waiting&q=agent"))[0] == []


async def test_badges_list_every_waiting_conversation_with_its_desk_and_holder_and_nothing_else(client, people, uow_factory):
    desk, other_desk, now = make_binding(org_id=1, graph_id=5), make_binding(org_id=1, graph_id=5), utcnow()
    waiting = [make_conversation(desk, mode="awaiting_human", last_message_at=now), make_conversation(desk, mode="awaiting_human"), _held(other_desk, 2, now, waiting=True)]
    # In progress is not counted: answered conversations nobody released would pile up in it.
    not_counted = [
        _held(desk, 1, now), _held(other_desk, 2, now), make_conversation(desk, last_message_at=now), make_conversation(desk, mode="awaiting_human", is_test=True, last_message_at=now), _held(desk, 2, now, is_test=True, waiting=True),
        make_closed(desk, mode="awaiting_human", last_message_at=now), make_closed(other_desk, reason="resolved", mode="human", assigned_operator_id=2, last_message_at=now),
    ]
    await _seed(uow_factory, desk, [c for c in [*waiting, *not_counted] if c.binding_id == desk.id])
    await _seed(uow_factory, other_desk, [c for c in [*waiting, *not_counted] if c.binding_id == other_desk.id])
    badges = await client.get(f"{BASE}/inbox/badges", headers=h("agent"))
    assert badges.status_code == 200 and set(badges.json()) == {"waiting"}
    assert sorted((b["id"], b["binding_id"], b["assigned_operator_id"]) for b in badges.json()["waiting"]) == sorted((str(c.id), str(c.binding_id), c.assigned_operator_id) for c in waiting)


async def test_badges_need_chats_read_and_show_another_org_nothing(client, people, uow_factory):
    binding, now = make_binding(org_id=1, graph_id=5), utcnow()
    await _seed(uow_factory, binding, [make_conversation(binding, mode="awaiting_human", last_message_at=now), _held(binding, 1, now)])
    assert (await client.get(f"{BASE}/inbox/badges", headers=h("admin", org=2))).json() == {"waiting": []}
    assert (await client.get(f"{BASE}/inbox/badges", headers=h("agent", org=2))).status_code == 404
    assert (await client.get(f"{BASE}/inbox/badges", headers=h("viewer"))).status_code == 403
    assert (await client.get(f"{BASE}/inbox/badges")).status_code == 401
    assert (await client.get(f"{BASE}/inbox/badges?ticket=x")).status_code == 401  # the guarded route, not the stream's


async def test_search_and_mine_never_reach_another_org(client, people, uow_factory):
    org_one, org_two, now = make_binding(org_id=1, graph_id=5), make_binding(org_id=2, graph_id=6), utcnow()
    org_one_rows = [_held(org_one, 1, now, visitor_number=5), _held(org_one, 1, now, waiting=True, subject="customer-9", is_signed=True)]
    await _seed(uow_factory, org_one, org_one_rows)
    org_two_row = _held(org_two, 9, now, visitor_number=6)
    await _seed(uow_factory, org_two, [org_two_row])
    await _name(uow_factory, 1, "Ada Admin")
    as_org_two = h("admin", org=2)
    for query in ("section=in_progress&q=ada", "section=in_progress&q=5", "section=waiting&q=customer", "section=waiting&mine=true", "section=in_progress&mine=true", "section=waiting&q=ada&mine=true"):
        assert (await _walk(client, query, headers=as_org_two))[0] == [], query
    assert (await _walk(client, "section=in_progress", headers=as_org_two))[0] == [org_two_row.id]  # its own row only
    assert (await _walk(client, "section=in_progress&q=6"))[0] == []  # org one sees nothing of org two


@pytest.mark.parametrize("query, code", [
    ("section=human&mine=true", "validation_error"),
    ("section=human&q=ada", "validation_error"),
    ("section=bot&order=random", "validation_error"),
    ("section=waiting&q=" + "a" * 101, "invalid_search"),
    ("section=waiting&q=ada%00", "invalid_search"),
])
async def test_new_list_parameters_are_validated(client, people, query, code):
    refused = await client.get(f"{BASE}/conversations?{query}", headers=h("agent"))
    assert (refused.status_code, refused.json()["code"]) == (400, code)


async def test_a_blank_search_lists_the_section(client, people, uow_factory):
    binding = make_binding(org_id=1, graph_id=5)
    rows = _spread(binding, 3)
    await _seed(uow_factory, binding, rows)
    assert (await _walk(client, "section=bot&q=%20%20"))[0] == _bot_order(rows)


async def test_the_holder_name_search_and_row_names_use_only_names_known_in_the_callers_org(client, people, django, uow_factory):
    """Bea works in Acme only; Ada (admin) in Acme's sibling Beta. A name is known in an org once
    its operator acted there, and no org's search or rows ever see another org's names."""
    django.users["agent"]["display_name"] = "Bea Agent"
    django.users["admin"]["display_name"] = "Ada Admin"
    acme, beta, now = make_binding(org_id=1, graph_id=5), make_binding(org_id=2, graph_id=6), utcnow()
    in_acme, in_beta = make_conversation(acme, mode="awaiting_human", last_message_at=now), make_conversation(beta, mode="awaiting_human", last_message_at=now)
    await _seed(uow_factory, acme, [in_acme])
    await _seed(uow_factory, beta, [in_beta])
    for conversation, user, org in ((in_acme, "agent", 1), (in_beta, "admin", 2)):
        assert (await client.post(f"{BASE}/conversations/{conversation.id}/claim", json={}, headers=h(user, org))).status_code == 200
        assert (await client.post(f"{BASE}/conversations/{conversation.id}/messages", json={"content": "Hi"}, headers=h(user, org))).status_code == 201
    as_acme, as_beta = h("admin", 1), h("admin", 2)
    assert (await _walk(client, "section=in_progress&q=bea", headers=as_acme))[0] == [in_acme.id]
    assert (await _walk(client, "section=in_progress&q=bea", headers=as_beta))[0] == []
    assert (await _walk(client, "section=in_progress&q=ada", headers=as_beta))[0] == [in_beta.id]
    assert (await _walk(client, "section=in_progress&q=ada", headers=as_acme))[0] == []  # Ada never acted in Acme
    beta_page = (await client.get(f"{BASE}/conversations?section=in_progress", headers=as_beta)).json()
    assert "Bea" not in str(beta_page) and beta_page["results"][0]["assigned_operator_name"] == "Ada Admin"


# ---- operator aliases per desk -------------------------------------------------------------------

def _my_alias(binding_id):
    return f"{BASE}/bindings/{binding_id}/my-alias"


async def test_an_operator_sets_and_clears_their_name_on_a_desk(client, people):
    binding = await _active_binding(client)
    named = await client.put(_my_alias(binding["id"]), json={"alias": "  Mike  "}, headers=h("agent"))
    assert named.status_code == 200, named.text
    assert named.json() == {"binding_id": binding["id"], "alias": "Mike", "visible_name": "Mike"}
    # A static path: the desk route's uuid converter must not take "my-aliases" for an id.
    assert (await client.get(f"{BASE}/bindings/my-aliases", headers=h("agent"))).json() == [{"binding_id": binding["id"], "alias": "Mike"}]
    assert (await client.get(f"{BASE}/bindings/my-aliases", headers=h("admin"))).json() == []  # one's own aliases only
    for cleared_with in (None, "   "):
        cleared = await client.put(_my_alias(binding["id"]), json={"alias": cleared_with}, headers=h("agent"))
        assert cleared.json() == {"binding_id": binding["id"], "alias": None, "visible_name": "Support"}
    assert (await client.get(f"{BASE}/bindings/my-aliases", headers=h("agent"))).json() == []


async def test_an_alias_another_operator_holds_on_the_desk_is_taken_in_any_case(client, people):
    binding, other = await _live_bindings(client)
    assert (await client.put(_my_alias(binding["id"]), json={"alias": "Mike"}, headers=h("agent"))).status_code == 200
    taken = await client.put(_my_alias(binding["id"]), json={"alias": "MIKE"}, headers=h("admin"))
    assert (taken.status_code, taken.json()["code"]) == (409, "alias_taken")
    assert (await client.put(_my_alias(other["id"]), json={"alias": "Mike"}, headers=h("admin"))).status_code == 200  # another desk
    own = await client.put(_my_alias(binding["id"]), json={"alias": "MIKE"}, headers=h("agent"))  # one's own, new case
    assert (own.status_code, own.json()["alias"]) == (200, "MIKE")


async def test_the_desks_bot_name_is_reserved(client, people):
    binding = (await client.post(f"{BASE}/bindings", json={**NEW_BINDING, "bot_display_name": "Ava"}, headers=h("admin"))).json()
    reserved = await client.put(_my_alias(binding["id"]), json={"alias": "aVA"}, headers=h("agent"))
    assert (reserved.status_code, reserved.json()["code"]) == (409, "alias_reserved")
    assert (await client.get(f"{BASE}/bindings/my-aliases", headers=h("agent"))).json() == []


@pytest.mark.parametrize("body", [{"alias": "x" * 65}, {"alias": "\u202eekiM"}, {"alias": "Mi\nke"}, {}, {"alias": 7}], ids=["too long", "bidi override", "newline", "no alias key", "not a string"])
async def test_an_invalid_alias_is_400_and_stores_nothing(client, people, body):
    binding = await _active_binding(client)
    refused = await client.put(_my_alias(binding["id"]), json=body, headers=h("agent"))
    assert (refused.status_code, refused.json()["code"]) == (400, "validation_error") and refused.json()["errors"]
    assert (await client.get(f"{BASE}/bindings/my-aliases", headers=h("agent"))).json() == []


async def test_an_alias_takes_chats_use_and_stays_inside_the_org(client, people, django):
    django.users["reader"] = {"active": True, "user_id": 6, "email": "r@x", "scopes": [], "org_ids": [1], "is_superadmin": False}
    django.permissions[("reader", 1)] = {"chats": ["read"]}
    binding = await _active_binding(client)
    foreign = (await client.post(f"{BASE}/bindings", json={**NEW_BINDING, "graph_id": 6}, headers=h("admin", org=2))).json()
    assert (await client.put(_my_alias(binding["id"]), json={"alias": "Mike"}, headers=h("reader"))).status_code == 403
    assert (await client.get(f"{BASE}/bindings/my-aliases", headers=h("reader"))).status_code == 200
    assert (await client.get(f"{BASE}/bindings/my-aliases", headers=h("viewer"))).status_code == 403
    assert (await client.put(_my_alias(foreign["id"]), json={"alias": "Mike"}, headers=h("admin", org=1))).status_code == 404
    assert (await client.put(_my_alias(foreign["id"]), json={"alias": "Mikko"}, headers=h("admin", org=2))).status_code == 200
    assert (await client.put(_my_alias(binding["id"]), json={"alias": "Mike"}, headers=h("admin", org=1))).status_code == 200
    assert (await client.get(f"{BASE}/bindings/my-aliases", headers=h("admin", org=1))).json() == [{"binding_id": binding["id"], "alias": "Mike"}]
    assert (await client.get(f"{BASE}/bindings/my-aliases", headers=h("admin", org=2))).json() == [{"binding_id": foreign["id"], "alias": "Mikko"}]


async def test_each_reply_keeps_the_name_it_was_sent_with(client, people, uow_factory):
    binding = await _active_binding(client)
    conversation_id = (await client.post(f"{BASE}/bindings/{binding['id']}/test-conversation", headers=h("admin"))).json()["conversation"]["id"]
    await client.post(f"{BASE}/conversations/{conversation_id}/claim", json={}, headers=h("agent"))

    async def reply(content):
        sent = await client.post(f"{BASE}/conversations/{conversation_id}/messages", json={"content": content}, headers=h("agent"))
        assert sent.status_code == 201
        return sent.json()

    await client.put(_my_alias(binding["id"]), json={"alias": "Mike"}, headers=h("agent"))
    first = await reply("one")
    assert first["visible_name"] == "Mike"
    await client.put(_my_alias(binding["id"]), json={"alias": "Mikey"}, headers=h("agent"))
    await client.patch(f"{BASE}/bindings/{binding['id']}", json={"operator_display_name": "Team"}, headers=h("admin"))
    second = await reply("two")
    await client.put(_my_alias(binding["id"]), json={"alias": None}, headers=h("agent"))
    third = await reply("three")
    page = (await client.get(f"{BASE}/conversations/{conversation_id}/messages", headers=h("agent"))).json()
    assert [(m["content"], m["visible_name"]) for m in page] == [("one", "Mike"), ("two", "Mikey"), ("three", "Team")]
    assert (second["visible_name"], third["visible_name"]) == ("Mikey", "Team")
    created = [e for e in await _inbox(uow_factory, UUID(conversation_id), "message.created")]
    assert [e["visible_name"] for e in created] == ["Mike", "Mikey", "Team"]


@pytest.mark.parametrize("field", ["bot_display_name", "operator_display_name"])
@pytest.mark.parametrize("value", ["\u202eekiM", "Team\u200b", "Te\tam"], ids=["bidi override", "zero width space", "tab"])
async def test_the_desks_names_follow_the_same_rules_as_an_alias(client, people, field, value):
    refused = await client.post(f"{BASE}/bindings", json={**NEW_BINDING, field: value}, headers=h("admin"))
    assert (refused.status_code, refused.json()["code"]) == (400, "validation_error")
    binding = await _active_binding(client)
    patched = await client.patch(f"{BASE}/bindings/{binding['id']}", json={field: value}, headers=h("admin"))
    assert patched.status_code == 400
    joined = await client.patch(f"{BASE}/bindings/{binding['id']}", json={field: "\U0001f469\u200d\U0001f4bb Team"}, headers=h("admin"))
    assert joined.status_code == 200 and joined.json()[field] == "\U0001f469\u200d\U0001f4bb Team"


async def test_a_desk_name_that_cannot_be_the_bots_name_needs_one_given(client, people):
    refused = await client.post(f"{BASE}/bindings", json={**NEW_BINDING, "name": "Sales\u202e"}, headers=h("admin"))
    assert (refused.status_code, refused.json()["code"]) == (400, "validation_error") and "bot_display_name" in refused.json()["message"]
    created = await client.post(f"{BASE}/bindings", json={**NEW_BINDING, "name": "Sales\u202e", "bot_display_name": "Sales"}, headers=h("admin"))
    assert created.status_code == 201 and created.json()["bot_display_name"] == "Sales"


async def test_a_desks_bot_cannot_take_a_name_an_operator_uses_there(client, people):
    binding, other = await _live_bindings(client)
    assert (await client.put(_my_alias(binding["id"]), json={"alias": "Mike"}, headers=h("agent"))).status_code == 200
    refused = await client.patch(f"{BASE}/bindings/{binding['id']}", json={"bot_display_name": "mIKE", "name": "Renamed"}, headers=h("admin"))
    assert (refused.status_code, refused.json()["code"], refused.json()["field"]) == (409, "bot_name_taken", "bot_display_name")
    assert refused.json()["message"]
    stored = (await client.get(f"{BASE}/bindings/{binding['id']}", headers=h("admin"))).json()
    assert (stored["bot_display_name"], stored["name"]) == ("Support", "Support")  # nothing of the refused save was kept
    renamed = await client.patch(f"{BASE}/bindings/{binding['id']}", json={"bot_display_name": "Ava"}, headers=h("admin"))
    assert (renamed.status_code, renamed.json()["bot_display_name"]) == (200, "Ava")
    # Aliases are per desk: another desk's bot, and a new desk's, may use the name.
    assert (await client.patch(f"{BASE}/bindings/{other['id']}", json={"bot_display_name": "Mike"}, headers=h("admin"))).status_code == 200
    created = await client.post(f"{BASE}/bindings", json={**NEW_BINDING, "name": "Mike"}, headers=h("admin"))
    assert (created.status_code, created.json()["bot_display_name"]) == (201, "Mike")


def _desk_orchestrator(client):
    return build_bindings(client.app.state)


async def test_an_alias_claim_holding_the_desk_makes_a_bot_rename_onto_it_wait_and_fail(client, people, monkeypatch):
    binding = await _active_binding(client)
    claimed, proceed = asyncio.Event(), asyncio.Event()
    set_alias = OperatorAliasRepository.set

    async def set_then_hold(self, *args, **kwargs):
        await set_alias(self, *args, **kwargs)
        claimed.set()
        await proceed.wait()  # still inside the claim's transaction, holding the desk's shared lock

    monkeypatch.setattr(OperatorAliasRepository, "set", set_then_hold)
    desks = _desk_orchestrator(client)
    claim = asyncio.ensure_future(desks.set_my_alias(UUID(binding["id"]), 1, 2, "Mike"))
    await asyncio.wait_for(claimed.wait(), timeout=5)
    rename = asyncio.ensure_future(desks.update(UUID(binding["id"]), CallerCredentials(org_id=1, bearer_token="admin"), {"bot_display_name": "MIKE"}))
    done, _ = await asyncio.wait({rename}, timeout=0.3)
    assert not done, "the bot rename did not wait for the alias claim"
    proceed.set()
    assert await asyncio.wait_for(claim, timeout=5) == ("Mike", "Mike")
    with pytest.raises(BotNameTakenError):
        await asyncio.wait_for(rename, timeout=5)
    assert (await client.get(f"{BASE}/bindings/{binding['id']}", headers=h("admin"))).json()["bot_display_name"] == "Support"


async def test_a_bot_rename_holding_the_desk_makes_an_alias_claim_on_the_new_name_wait_and_fail(client, people, monkeypatch):
    binding = await _active_binding(client)
    checked, proceed = asyncio.Event(), asyncio.Event()
    is_taken = OperatorAliasRepository.is_taken

    async def check_then_hold(self, *args, **kwargs):
        taken = await is_taken(self, *args, **kwargs)
        checked.set()
        await proceed.wait()  # still inside the rename's transaction, holding the desk's row lock
        return taken

    monkeypatch.setattr(OperatorAliasRepository, "is_taken", check_then_hold)
    desks = _desk_orchestrator(client)
    rename = asyncio.ensure_future(desks.update(UUID(binding["id"]), CallerCredentials(org_id=1, bearer_token="admin"), {"bot_display_name": "Mike"}))
    await asyncio.wait_for(checked.wait(), timeout=5)
    claim = asyncio.ensure_future(desks.set_my_alias(UUID(binding["id"]), 1, 2, "mike"))
    done, _ = await asyncio.wait({claim}, timeout=0.3)
    assert not done, "the alias claim did not wait for the bot rename"
    proceed.set()
    renamed, _ = await asyncio.wait_for(rename, timeout=5)
    assert renamed.bot_display_name == "Mike"
    with pytest.raises(AliasReservedError):
        await asyncio.wait_for(claim, timeout=5)
    assert (await client.get(f"{BASE}/bindings/my-aliases", headers=h("agent"))).json() == []


SHARP_S, DOTTED_CAPITAL_I = chr(0xDF), chr(0x130)


@pytest.mark.parametrize(("bot", "alias", "same"), [
    ("Stra" + SHARP_S + "e", "STRASSE", True),
    (DOTTED_CAPITAL_I + "pek", DOTTED_CAPITAL_I + "PEK", True),
    (DOTTED_CAPITAL_I + "pek", "Ipek", False),
], ids=["sharp s", "dotted capital I", "plain I"])
async def test_alias_and_bot_name_clash_by_the_same_rule_in_both_directions(client, people, bot, alias, same):
    named_bot = (await client.post(f"{BASE}/bindings", json={**NEW_BINDING, "bot_display_name": bot}, headers=h("admin"))).json()
    claimed = await client.put(_my_alias(named_bot["id"]), json={"alias": alias}, headers=h("agent"))
    assert (claimed.status_code, claimed.json().get("code")) == ((409, "alias_reserved") if same else (200, None))
    aliased = await _active_binding(client)
    assert (await client.put(_my_alias(aliased["id"]), json={"alias": alias}, headers=h("agent"))).status_code == 200
    renamed = await client.patch(f"{BASE}/bindings/{aliased['id']}", json={"bot_display_name": bot}, headers=h("admin"))
    assert (renamed.status_code, renamed.json().get("code")) == ((409, "bot_name_taken") if same else (200, None))


async def test_an_alias_cannot_copy_the_bots_name_with_an_invisible_character(client, people):
    binding = (await client.post(f"{BASE}/bindings", json={**NEW_BINDING, "bot_display_name": "Ava"}, headers=h("admin"))).json()
    filler = await client.put(_my_alias(binding["id"]), json={"alias": "Ava" + chr(0x3164)}, headers=h("agent"))
    assert (filler.status_code, filler.json()["code"]) == (400, "validation_error")
    joined = await client.put(_my_alias(binding["id"]), json={"alias": "Ava" + chr(0x200D)}, headers=h("agent"))
    assert (joined.status_code, joined.json()["code"]) == (409, "alias_reserved")
    technologist = chr(0x1F469) + chr(0x200D) + chr(0x1F4BB) + " " + chr(0x2764) + chr(0xFE0F)
    kept = await client.put(_my_alias(binding["id"]), json={"alias": technologist}, headers=h("agent"))
    assert (kept.status_code, kept.json()["alias"]) == (200, technologist)


# ---- closing a conversation, and reading one --------------------------------------------------------

CLOSE_FIELDS = ("status", "close_reason", "closed_by_user_id", "closed_by_name")


def _close(conversation_id):
    return f"{BASE}/conversations/{conversation_id}/close"


async def test_resolving_closes_the_conversation_names_who_did_it_and_stops_the_run(client, people, django, uow_factory):
    django.users["agent"]["display_name"] = "Bea Agent"
    binding = await _active_binding(client)
    test = (await client.post(f"{BASE}/bindings/{binding['id']}/test-conversation", headers=h("admin"))).json()
    conversation_id, visitor = test["conversation"]["id"], {"Authorization": f"Bearer {test['visitor_token']}"}
    assert (await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json={"content": "help"}, headers=visitor)).json()["state"] == "processing"

    closed = await client.post(_close(conversation_id), headers=h("agent"))  # no body: force is false
    assert closed.status_code == 200, closed.text
    row = closed.json()
    assert {field: row[field] for field in CLOSE_FIELDS} == {"status": "closed", "close_reason": "resolved", "closed_by_user_id": 2, "closed_by_name": "Bea Agent"}
    assert (row["state"], row["mode"]) == ("idle", "bot") and row["closed_at"] is not None
    assert django.stopped == [100]
    assert (await client.get(f"{BASE}/conversations/{conversation_id}", headers=h("admin"))).json() == row
    updates = await _inbox(uow_factory, UUID(conversation_id), "conversation.updated")
    assert ConversationOutput.model_validate(updates[-1]).model_dump(mode="json") == row
    (announced,) = await _inbox(uow_factory, UUID(conversation_id), "conversation.closed")
    assert announced == {"conversation_id": conversation_id, "close_reason": "resolved", "closed_at": announced["closed_at"], "closed_by_user_id": 2}
    async with uow_factory() as uow:
        visitor_events = await uow.events.replay(Stream.CONVERSATION, conversation_id=UUID(conversation_id), after_seq=None)
    assert [(e.type, e.payload) for e in visitor_events][-2:] == [("run.finished", {"status": "stop"}), ("conversation.closed", {"close_reason": "resolved", "closed_at": announced["closed_at"]})]

    # Idempotent: closing again, by anyone, answers the same row and announces nothing.
    again = await client.post(_close(conversation_id), json={"force": True}, headers=h("admin"))
    assert (again.status_code, again.json()) == (200, row)
    assert len(await _inbox(uow_factory, UUID(conversation_id), "conversation.closed")) == 1
    state = (await client.get(f"/chat/public/v1/conversations/{conversation_id}", headers=visitor)).json()
    assert (state["status"], state["close_reason"]) == ("closed", "resolved")


async def test_closing_one_another_operator_holds_takes_force_and_keeps_the_holder(client, people, uow_factory):
    binding, now = make_binding(org_id=1, graph_id=5), utcnow()
    theirs, mine = _held(binding, 2, now), _held(binding, 1, now)
    await _seed(uow_factory, binding, [theirs, mine])
    refused = await client.post(_close(theirs.id), json={}, headers=h("admin"))
    assert (refused.status_code, refused.json()["code"]) == (409, "claimed_by_other")
    assert (await client.get(f"{BASE}/conversations/{theirs.id}", headers=h("admin"))).json()["status"] == "open"
    forced = (await client.post(_close(theirs.id), json={"force": True}, headers=h("admin"))).json()
    assert (forced["status"], forced["closed_by_user_id"], forced["assigned_operator_id"], forced["mode"]) == ("closed", 1, 2, "human")
    own = await client.post(_close(mine.id), json={}, headers=h("admin"))  # one's own needs no force
    assert (own.status_code, own.json()["closed_by_user_id"]) == (200, 1)


async def test_closing_takes_chats_use_while_reading_one_conversation_takes_chats_read(client, people, django, uow_factory):
    django.users["reader"] = {"active": True, "user_id": 6, "email": "r@x", "scopes": [], "org_ids": [1], "is_superadmin": False}
    django.permissions[("reader", 1)] = {"chats": ["read"]}
    binding = make_binding(org_id=1, graph_id=5)
    conversation = make_conversation(binding, mode="awaiting_human", last_message_at=utcnow())
    await _seed(uow_factory, binding, [conversation])
    refused = await client.post(_close(conversation.id), json={}, headers=h("reader"))
    assert (refused.status_code, refused.json()["code"]) == (403, "forbidden")
    assert (await client.get(f"{BASE}/conversations/{conversation.id}", headers=h("reader"))).status_code == 200


async def test_closing_and_reading_another_orgs_conversation_is_404_and_leaves_it_open(client, people, uow_factory):
    beta = make_binding(org_id=2, graph_id=6)
    conversation = make_conversation(beta, mode="awaiting_human", last_message_at=utcnow())
    await _seed(uow_factory, beta, [conversation])
    for response in (await client.post(_close(conversation.id), json={"force": True}, headers=h("agent")), await client.get(f"{BASE}/conversations/{conversation.id}", headers=h("admin", org=1))):
        assert (response.status_code, response.json()["code"]) == (404, "not_found")
    assert (await client.get(f"{BASE}/conversations/{conversation.id}", headers=h("admin", org=2))).json()["status"] == "open"
    assert await _inbox(uow_factory, conversation.id, "conversation.closed") == []


@pytest.mark.parametrize(("action", "mode"), [("claim", "human"), ("claim", "awaiting_human"), ("release", "human"), ("release", "bot"), ("messages", "human")])
async def test_taking_releasing_or_replying_to_a_closed_conversation_is_409(client, people, uow_factory, action, mode):
    binding = make_binding(org_id=1, graph_id=5)
    closed = make_closed(binding, reason="ended", mode=mode, **({"assigned_operator_id": 2} if mode == "human" else {}), last_message_at=utcnow())
    await _seed(uow_factory, binding, [closed])
    body = {"content": "hi"} if action == "messages" else {}
    refused = await client.post(f"{BASE}/conversations/{closed.id}/{action}", json=body, headers=h("agent"))
    assert (refused.status_code, refused.json()["code"], refused.json()["close_reason"]) == (409, "conversation_closed", "ended")
    async with uow_factory() as uow:
        assert await uow.conversations.get(closed.id) == closed
        assert await uow.messages.page(closed.id, None, 10) == []


async def test_one_conversation_reads_as_the_row_its_section_lists_open_or_closed(client, people, django, uow_factory):
    django.users["agent"]["display_name"] = "Bea Agent"
    binding, now = make_binding(org_id=1, graph_id=5), utcnow()
    waiting = make_conversation(binding, mode="awaiting_human", last_message_at=now)
    resolved = make_closed(binding, reason="resolved", mode="human", assigned_operator_id=1, closed_by_user_id=2, last_message_at=now)
    await _seed(uow_factory, binding, [waiting, resolved])
    await _name(uow_factory, 2, "Bea Agent")
    for section, conversation in (("waiting", waiting), ("closed", resolved)):
        read = await client.get(f"{BASE}/conversations/{conversation.id}", headers=h("agent"))
        assert read.status_code == 200 and read.json() == await _listed(client, section, conversation.id), section
    assert (await client.get(f"{BASE}/conversations/{resolved.id}", headers=h("agent"))).json()["closed_by_name"] == "Bea Agent"
    assert (await client.get(f"{BASE}/conversations/{new_id()}", headers=h("agent"))).status_code == 404


async def test_closed_lists_the_most_recently_closed_first_whatever_the_order(client, people, uow_factory):
    binding, start = make_binding(org_id=1, graph_id=5), utcnow()
    # Threes share a close time, so the page boundary splits one; activity runs the other way.
    rows = [make_closed(binding, closed_at=start - timedelta(seconds=index // 3), last_message_at=start - timedelta(days=1, seconds=-index)) for index in range(PAGE_SIZE + 5)]
    await _seed(uow_factory, binding, [*rows, make_closed(binding, is_test=True, last_message_at=start)])
    expected = [c.id for c in sorted(rows, key=lambda c: (c.closed_at, c.id), reverse=True)]
    for query in ("section=closed", "section=closed&order=newest", "section=closed&order=oldest", f"section=closed&binding={binding.id}"):
        assert await _walk(client, query) == (expected, [PAGE_SIZE, 5]), query
    assert (await _walk(client, "section=closed", headers=h("admin", org=2)))[0] == []


async def test_search_and_mine_reach_closed_conversations_and_nothing_of_another_org(client, people, uow_factory):
    binding, now = make_binding(org_id=1, graph_id=5), utcnow()
    held_by_bea = make_closed(binding, reason="resolved", mode="human", assigned_operator_id=2, visitor_number=12, subject="customer-12", is_signed=True, last_message_at=now)
    held_by_ada = make_closed(binding, mode="human", assigned_operator_id=1, visitor_number=13, last_message_at=now)
    from_the_bot = make_closed(binding, visitor_number=14, last_message_at=now)
    open_held_by_bea = _held(binding, 2, now)
    await _seed(uow_factory, binding, [held_by_bea, held_by_ada, from_the_bot, open_held_by_bea])
    await _name(uow_factory, 2, "Bea Agent")
    assert (await _walk(client, "section=closed&mine=true"))[0] == [held_by_bea.id]  # the agent is Bea
    for q in ("bea", "12", "Customer-1"):
        assert (await _walk(client, f"section=closed&q={q}"))[0] == [held_by_bea.id], q
    assert (await _walk(client, "section=closed&q=14"))[0] == [from_the_bot.id]
    assert (await _walk(client, "section=in_progress&q=bea"))[0] == [open_held_by_bea.id]
    assert (await _walk(client, "section=closed&q=bea", headers=h("admin", org=2)))[0] == []


# ---- a desk's style and inactivity rules ------------------------------------------------------------

RULES = ("style", "response_time_seconds", "on_response_timeout", "handback_message", "close_after_seconds")


async def test_a_desk_can_name_its_own_style_and_rules_on_create_and_change_them(client, people):
    own = {"style": "ongoing", "response_time_seconds": 120, "on_response_timeout": "wait", "handback_message": "", "close_after_seconds": 3600}
    created = await client.post(f"{BASE}/bindings", json={**NEW_BINDING, **own}, headers=h("admin"))
    assert created.status_code == 201 and {name: created.json()[name] for name in RULES} == own
    changes = {"style": "support", "on_response_timeout": "overdue", "response_time_seconds": 300, "handback_message": "Back soon"}
    patched = await client.patch(f"{BASE}/bindings/{created.json()['id']}", json=changes, headers=h("admin"))
    assert patched.status_code == 200 and {name: patched.json()[name] for name in RULES} == {**own, **changes}
    stored = (await client.get(f"{BASE}/bindings/{created.json()['id']}", headers=h("agent"))).json()
    assert {name: stored[name] for name in RULES} == {**own, **changes}


@pytest.mark.parametrize("name", ["response_time_seconds", "close_after_seconds"])
async def test_a_duration_above_the_deployments_cap_is_refused_on_create_and_patch(client, people, settings, name):
    cap = {"response_time_seconds": settings.CHAT_RESPONSE_TIME_MAX, "close_after_seconds": settings.CHAT_CLOSE_AFTER_MAX}[name]
    above = await client.post(f"{BASE}/bindings", json={**NEW_BINDING, name: cap + 1}, headers=h("admin"))
    assert above.status_code == 400
    assert above.json() == {"code": "duration_above_cap", "message": f"`{name}` cannot exceed {cap} seconds on this deployment.", "field": name, "max": cap}
    assert (await client.get(f"{BASE}/bindings", headers=h("admin"))).json() == []
    at_cap = await client.post(f"{BASE}/bindings", json={**NEW_BINDING, name: cap}, headers=h("admin"))
    assert at_cap.status_code == 201 and at_cap.json()[name] == cap
    refused = await client.patch(f"{BASE}/bindings/{at_cap.json()['id']}", json={name: cap + 1, "name": "Renamed"}, headers=h("admin"))
    assert (refused.status_code, refused.json()["code"], refused.json()["field"], refused.json()["max"]) == (400, "duration_above_cap", name, cap)
    stored = (await client.get(f"{BASE}/bindings/{at_cap.json()['id']}", headers=h("admin"))).json()
    assert (stored[name], stored["name"]) == (cap, "Support")


@pytest.mark.parametrize("rule", [
    {"response_time_seconds": 59}, {"close_after_seconds": 0}, {"response_time_seconds": None}, {"close_after_seconds": None},
    {"style": "sometimes"}, {"on_response_timeout": "escalate"}, {"handback_message": "x" * 4001}, {"handback_message": "hi\x00"},
    {"style": None}, {"on_response_timeout": None}, {"handback_message": None},
], ids=["response time under a minute", "close after zero", "null response time", "null close after", "unknown style", "unknown action", "notice too long", "notice with NUL", "null style", "null action", "null notice"])
async def test_an_invalid_rule_is_400_on_create_and_patch_and_stores_nothing(client, people, rule):
    refused = await client.post(f"{BASE}/bindings", json={**NEW_BINDING, **rule}, headers=h("admin"))
    assert (refused.status_code, refused.json()["code"]) == (400, "validation_error")
    binding = (await client.post(f"{BASE}/bindings", json=NEW_BINDING, headers=h("admin"))).json()
    assert (await client.patch(f"{BASE}/bindings/{binding['id']}", json=rule, headers=h("admin"))).status_code == 400
    stored = (await client.get(f"{BASE}/bindings/{binding['id']}", headers=h("admin"))).json()
    assert {name: stored[name] for name in RULES} == {name: binding[name] for name in RULES}


@pytest.mark.parametrize("name", RULES)
async def test_patch_refuses_a_null_rule(client, people, name):
    binding = (await client.post(f"{BASE}/bindings", json=NEW_BINDING, headers=h("admin"))).json()
    refused = await client.patch(f"{BASE}/bindings/{binding['id']}", json={name: None}, headers=h("admin"))
    assert (refused.status_code, refused.json()["code"]) == (400, "validation_error") and name in refused.json()["message"]
