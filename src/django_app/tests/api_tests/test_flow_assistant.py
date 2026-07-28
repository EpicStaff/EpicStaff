"""
Integration tests for the Flow Assistant feature.

Mocks: LLM client only.
Real: ORM, serializers, views, URL routing.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from tables.models import (
    Graph,
    LLMConfig,
    LLMModel,
    Organization,
    OrganizationUser,
    Provider,
    Role,
)
from tables.models.flow_assistant_models import (
    FlowAssistant,
    FlowAssistantConversation,
    FlowAssistantMessage,
)
from tables.services.flow_assistant import FlowAssistantService
from tables.services.llm_clients.base import (
    DoneEvent,
    StructuredEvent,
    TokenEvent,
    ToolCallEvent,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def openai_provider(db):
    return Provider.objects.create(name="openai")


@pytest.fixture
def gpt4_model(openai_provider):
    return LLMModel.objects.create(name="gpt-4o", llm_provider=openai_provider)


@pytest.fixture
def llm_config(gpt4_model):
    return LLMConfig.objects.create(
        custom_name="test-gpt4o",
        model=gpt4_model,
        temperature=0.5,
    )


@pytest.fixture
def graph(db):
    return Graph.objects.create(name="Test Flow", description="A test flow.")


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


@pytest.fixture
def default_role(db):
    return Role.objects.get_or_create(name="member")[0]


@pytest.fixture
def user_a(db):
    return get_user_model().objects.create_user(
        email="user_a@test.com", password="Pass1234!"
    )


@pytest.fixture
def user_b(db):
    return get_user_model().objects.create_user(
        email="user_b@test.com", password="Pass1234!"
    )


@pytest.fixture
def superadmin_user(db):
    user = get_user_model().objects.create_user(
        email="superadmin@test.com", password="Pass1234!"
    )
    user.is_superadmin = True
    user.save()
    return user


@pytest.fixture
def org_user_a(user_a, org_a, default_role):
    return OrganizationUser.objects.create(user=user_a, org=org_a, role=default_role)


@pytest.fixture
def org_user_a_in_org_b(user_a, org_b, default_role):
    """UserA membership in Org B — separate membership row."""
    return OrganizationUser.objects.create(user=user_a, org=org_b, role=default_role)


@pytest.fixture
def org_user_b(user_b, org_a, default_role):
    return OrganizationUser.objects.create(user=user_b, org=org_a, role=default_role)


@pytest.fixture
def superadmin_org_user(superadmin_user, org_a, default_role):
    return OrganizationUser.objects.create(
        user=superadmin_user, org=org_a, role=default_role
    )


@pytest.fixture
def auth_client_a(user_a, org_user_a):
    """Client for user_a in org_a (single org → no header needed)."""
    client = APIClient()
    refresh = RefreshToken.for_user(user_a)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
    return client


@pytest.fixture
def auth_client_a_org_b(user_a, org_user_a, org_user_a_in_org_b):
    """Client for user_a explicitly targeting org_b via header."""
    client = APIClient()
    refresh = RefreshToken.for_user(user_a)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
    client.defaults["HTTP_X_ORGANIZATION_ID"] = str(org_user_a_in_org_b.org_id)
    return client


@pytest.fixture
def auth_client_b(user_b, org_user_b):
    client = APIClient()
    refresh = RefreshToken.for_user(user_b)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
    return client


@pytest.fixture
def auth_client_superadmin(superadmin_user, superadmin_org_user):
    client = APIClient()
    refresh = RefreshToken.for_user(superadmin_user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
    return client


@pytest.fixture
def anon_client():
    return APIClient()


@pytest.fixture
def flow_assistant(graph, llm_config):
    return FlowAssistant.objects.create(graph=graph, llm_config=llm_config)


@pytest.fixture
def conversation_a(flow_assistant, org_user_a):
    return _make_conversation_with_messages(
        flow_assistant,
        org_user_a,
        [{"role": "system", "content": "You are the test flow."}],
    )


def _make_async_stream(*events):
    """Return an async generator that yields the given events."""

    async def _gen(messages, tools):
        for event in events:
            yield event

    return _gen


def _make_conversation_with_messages(
    flow_assistant, organization_user, messages, **extra
):
    """Create a conversation and bulk-create its message rows from a list of dicts.

    Drop-in replacement for FlowAssistantConversation.objects.create(..., messages=[...]).
    """
    conv = FlowAssistantConversation.objects.create(
        flow_assistant=flow_assistant,
        organization_user=organization_user,
        **extra,
    )
    rows = []
    for idx, msg in enumerate(messages):
        rows.append(
            FlowAssistantMessage(
                conversation=conv,
                message_index=idx,
                role=msg["role"],
                content=msg.get("content", ""),
                tool_calls=msg.get("tool_calls"),
                tool_call_id=msg.get("tool_call_id") or None,
                name=msg.get("name") or None,
                ef_tables=msg.get("ef_tables"),
                action_message=msg.get("action_message"),
                interrupted=bool(msg.get("interrupted", False)),
            )
        )
    if rows:
        FlowAssistantMessage.objects.bulk_create(rows)
    return conv


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_start_conversation_provisions_flow_assistant(
    graph, user_a, auth_client_a, org_user_a
):
    """POST without a prior FlowAssistant creates the row."""
    assert not FlowAssistant.objects.filter(graph=graph).exists()

    url = reverse("flow-assistant-conversations", kwargs={"graph_id": graph.pk})
    response = auth_client_a.post(url, {}, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert "conversation_id" in response.data
    assert FlowAssistant.objects.filter(graph=graph).exists()
    conversation = FlowAssistantConversation.objects.get(
        pk=response.data["conversation_id"]
    )
    assert conversation.organization_user == org_user_a
    # System prompt should be seeded as the first message
    assert conversation.messages[0]["role"] == "system"


@pytest.mark.django_db
def test_send_message_returns_stream_url(conversation_a, auth_client_a, graph):
    """POST a message returns {stream_url} with a ticket parameter."""
    url = reverse(
        "flow-assistant-send-message",
        kwargs={"graph_id": graph.pk, "conversation_id": conversation_a.pk},
    )
    # Patch SseTicketService.issue to avoid real Redis
    with patch(
        "tables.views.flow_assistant_views.SseTicketService.issue",
        return_value=("test-ticket-123", 30),
    ):
        response = auth_client_a.post(url, {"message": "Hello!"}, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert "stream_url" in response.data
    assert "test-ticket-123" in response.data["stream_url"]
    assert f"/conversations/{conversation_a.pk}/stream/" in response.data["stream_url"]

    # User message must be appended to conversation.messages
    conversation_a.refresh_from_db()
    user_msgs = [m for m in conversation_a.messages if m["role"] == "user"]
    assert user_msgs[-1]["content"] == "Hello!"


@pytest.mark.django_db
def test_get_node_redacts_secrets(graph, db):
    """get_node tool must redact api_key and token fields."""
    from tables.services.flow_assistant import get_node
    from tables.models.graph_models import CodeAgentNode

    node = CodeAgentNode.objects.create(
        graph=graph,
        node_name="secret_node",
        system_prompt="do stuff",
        stream_handler_code="",
    )

    result = get_node(graph.pk, str(node.pk))
    assert result.get("type") == "code_agent"
    # Any field with "api_key" in the name must be redacted
    config = result.get("config", {})
    for key, value in config.items():
        if (
            "api_key" in key.lower()
            or "secret" in key.lower()
            or "token" in key.lower()
        ):
            assert value == "***", f"Field '{key}' was not redacted: {value}"


@pytest.mark.django_db
def test_subflow_tool_overview_only(graph, db):
    """get_subflow returns name + description; no nodes/edges of the subgraph."""
    from tables.services.flow_assistant import get_subflow
    from tables.models.graph_models import SubGraphNode

    subgraph = Graph.objects.create(name="Child Flow", description="A child subflow.")
    sn = SubGraphNode.objects.create(
        graph=graph,
        subgraph=subgraph,
        node_name="sn_1",
    )

    result = get_subflow(graph.pk, str(sn.pk))
    assert result["name"] == "Child Flow"
    assert result["description"] == "A child subflow."
    # Must NOT contain node lists or edge lists
    assert "crew_node_list" not in result
    assert "edges" not in result
    assert "nodes" not in result


@pytest.mark.django_db
def test_permission_unauthenticated(graph, anon_client):
    """Anonymous requests must get 401."""
    url = reverse("flow-assistant-conversations", kwargs={"graph_id": graph.pk})
    response = anon_client.post(url, {}, format="json")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED, response.content


@pytest.mark.django_db
def test_conversation_belongs_to_org_user(conversation_a, auth_client_b, graph):
    """User B's client cannot access User A's conversation."""
    url = reverse(
        "flow-assistant-conversation",
        kwargs={"graph_id": graph.pk, "conversation_id": conversation_a.pk},
    )
    response = auth_client_b.get(url)
    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content


@pytest.mark.django_db
def test_get_flow_overview(graph, db):
    """get_flow_overview returns correct shape."""
    from tables.services.flow_assistant import get_flow_overview

    result = get_flow_overview(graph.pk)
    assert result["name"] == graph.name
    assert result["description"] == graph.description
    assert "node_count_by_type" in result
    assert "edge_count" in result
    assert isinstance(result["subflows"], list)


@pytest.mark.django_db
def test_list_node_types_empty(graph, db):
    """list_node_types on an empty graph returns an empty list."""
    from tables.services.flow_assistant import list_node_types

    result = list_node_types(graph.pk)
    assert isinstance(result, list)
    assert len(result) == 0


# ── Org-scope tests ───────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_org_scope_user_a_in_org_b_sees_no_conversations(
    graph,
    flow_assistant,
    conversation_a,
    auth_client_a_org_b,
    org_user_a,
    org_user_a_in_org_b,
):
    """UserA in OrgB has a separate membership → org-B conversations list is empty."""
    url = reverse("flow-assistant-conversations", kwargs={"graph_id": graph.pk})
    response = auth_client_a_org_b.get(url)
    assert response.status_code == status.HTTP_200_OK, response.content
    # conversation_a belongs to org_user_a (OrgA), not org_user_a_in_org_b (OrgB)
    assert response.data["count"] == 0


@pytest.mark.django_db
def test_org_scope_user_a_in_org_a_sees_own_conversations(
    graph, flow_assistant, conversation_a, auth_client_a
):
    """UserA in OrgA sees their own conversation in the list."""
    url = reverse("flow-assistant-conversations", kwargs={"graph_id": graph.pk})
    response = auth_client_a.get(url)
    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["count"] == 1
    assert response.data["results"][0]["id"] == conversation_a.pk


# ── Soft-delete tests ─────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_soft_delete_keeps_row_with_deleted_at(conversation_a, auth_client_a, graph):
    """DELETE sets deleted_at; row is preserved in DB."""
    url = reverse(
        "flow-assistant-conversation",
        kwargs={"graph_id": graph.pk, "conversation_id": conversation_a.pk},
    )
    response = auth_client_a.delete(url)
    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content

    conversation_a.refresh_from_db()
    assert conversation_a.deleted_at is not None


@pytest.mark.django_db
def test_soft_deleted_conversation_excluded_from_list(
    graph, flow_assistant, conversation_a, auth_client_a
):
    """Soft-deleted conversations do not appear in the GET list."""
    # Soft-delete the conversation
    from django.utils import timezone

    conversation_a.deleted_at = timezone.now()
    conversation_a.save(update_fields=["deleted_at"])

    url = reverse("flow-assistant-conversations", kwargs={"graph_id": graph.pk})
    response = auth_client_a.get(url)
    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["count"] == 0


@pytest.mark.django_db
def test_get_soft_deleted_conversation_returns_404(
    graph, flow_assistant, conversation_a, auth_client_a
):
    """GET on a soft-deleted conversation returns 404 (not visible to the user)."""
    from django.utils import timezone

    conversation_a.deleted_at = timezone.now()
    conversation_a.save(update_fields=["deleted_at"])

    url = reverse(
        "flow-assistant-conversation",
        kwargs={"graph_id": graph.pk, "conversation_id": conversation_a.pk},
    )
    response = auth_client_a.get(url)
    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


# ── Audit endpoint tests ──────────────────────────────────────────────────────


@pytest.mark.django_db
def test_audit_endpoint_superadmin_can_list(
    graph, flow_assistant, conversation_a, auth_client_superadmin
):
    """Superadmin can access the audit endpoint and see conversations."""
    url = reverse("flow-assistant-audit-conversations")
    response = auth_client_superadmin.get(url)
    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["count"] >= 1


@pytest.mark.django_db
def test_audit_endpoint_non_superadmin_gets_403(
    graph, flow_assistant, conversation_a, auth_client_a
):
    """Non-superadmin users receive 403 from the audit endpoint."""
    url = reverse("flow-assistant-audit-conversations")
    response = auth_client_a.get(url)
    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content


@pytest.mark.django_db
def test_audit_endpoint_includes_deleted_when_requested(
    graph, flow_assistant, conversation_a, auth_client_superadmin
):
    """include_deleted=true shows soft-deleted rows."""
    from django.utils import timezone

    conversation_a.deleted_at = timezone.now()
    conversation_a.save(update_fields=["deleted_at"])

    url = reverse("flow-assistant-audit-conversations")
    response = auth_client_superadmin.get(url, {"include_deleted": "true"})
    assert response.status_code == status.HTTP_200_OK, response.content
    ids = [r["id"] for r in response.data["results"]]
    assert conversation_a.pk in ids


@pytest.mark.django_db
def test_audit_endpoint_excludes_deleted_by_default(
    graph, flow_assistant, conversation_a, auth_client_superadmin
):
    """Without include_deleted, soft-deleted rows are hidden from audit list."""
    from django.utils import timezone

    conversation_a.deleted_at = timezone.now()
    conversation_a.save(update_fields=["deleted_at"])

    url = reverse("flow-assistant-audit-conversations")
    response = auth_client_superadmin.get(url)
    assert response.status_code == status.HTTP_200_OK, response.content
    ids = [r["id"] for r in response.data["results"]]
    assert conversation_a.pk not in ids


# ── Title auto-derivation tests ───────────────────────────────────────────────


@pytest.mark.django_db
def test_title_derived_from_first_user_message(
    graph, flow_assistant, conversation_a, auth_client_a
):
    """First user message causes title to be set on the conversation."""
    url = reverse(
        "flow-assistant-send-message",
        kwargs={"graph_id": graph.pk, "conversation_id": conversation_a.pk},
    )
    with patch(
        "tables.views.flow_assistant_views.SseTicketService.issue",
        return_value=("ticket-xyz", 30),
    ):
        response = auth_client_a.post(
            url,
            {"message": "Hello, what does this flow do?"},
            format="json",
        )

    assert response.status_code == status.HTTP_200_OK, response.content
    conversation_a.refresh_from_db()
    assert conversation_a.title != ""
    # Title should start with the message text (truncated)
    assert conversation_a.title.startswith("Hello")


@pytest.mark.django_db
def test_title_truncated_at_word_boundary():
    """_derive_title truncates at word boundary and appends ellipsis."""
    from tables.services.flow_assistant import _derive_title

    long_message = "Hello what does this flow do it seems very complicated"
    title = _derive_title(long_message)
    assert len(title) <= 52  # 50 chars + "…" is 1 char = 51 max; allow margin
    assert title.endswith("…")
    # No mid-word cut
    assert not title[:-1].endswith("-")


@pytest.mark.django_db
def test_title_not_overwritten_on_second_message(
    graph, flow_assistant, conversation_a, auth_client_a
):
    """Sending a second message does not change the already-set title."""
    conversation_a.title = "First title"
    conversation_a.save(update_fields=["title"])

    url = reverse(
        "flow-assistant-send-message",
        kwargs={"graph_id": graph.pk, "conversation_id": conversation_a.pk},
    )
    with patch(
        "tables.views.flow_assistant_views.SseTicketService.issue",
        return_value=("ticket-xyz2", 30),
    ):
        auth_client_a.post(
            url,
            {"message": "A completely different second message that is long enough"},
            format="json",
        )

    conversation_a.refresh_from_db()
    assert conversation_a.title == "First title"


# ── Async / streaming tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stream_yields_tokens_and_done(
    graph, llm_config, user_a, org_a, default_role, db
):
    """Stub LLM → plain-text [TokenEvent('hi'), DoneEvent()] → stream_reply emits
    a terminal StructuredEvent(message='hi') followed by DoneEvent.

    When the model ignores response_format and returns free-form text, the
    partial-JSON extractor finds no `message` field delta, so no TokenEvents
    are forwarded during streaming.  The fallback branch must emit one
    StructuredEvent carrying the full joined text before DoneEvent so the
    frontend renders a non-empty bubble.
    """
    from tables.services.flow_assistant import FlowAssistantService
    from tables.models.flow_assistant_models import (
        FlowAssistant,
        FlowAssistantConversation,
    )
    from asgiref.sync import sync_to_async

    user_message = "what does this flow do?"

    org_user = await sync_to_async(OrganizationUser.objects.create)(
        user=user_a, org=org_a, role=default_role
    )
    assistant = await sync_to_async(FlowAssistant.objects.create)(
        graph=graph, llm_config=llm_config
    )
    conversation = await sync_to_async(_make_conversation_with_messages)(
        assistant,
        org_user,
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": user_message},
        ],
    )

    async def fake_stream(messages, tools):
        yield TokenEvent(content="hi")
        yield DoneEvent()

    with patch(
        "tables.services.flow_assistant.service.get_llm_client"
    ) as mock_get_client:
        mock_client = MagicMock()
        mock_client.stream_completion = fake_stream
        mock_get_client.return_value = mock_client

        service = FlowAssistantService()
        events = []
        async for event in service.stream_reply(conversation, user_message):
            events.append(event)

    types = [e.type for e in events]

    # Terminal StructuredEvent must carry the plain-text content.
    structured_events = [e for e in events if e.type == "structured"]
    assert len(structured_events) == 1
    assert structured_events[0].message == "hi"
    assert structured_events[0].ef_tables == []
    assert structured_events[0].action_message == []

    # DoneEvent must be the last event.
    assert types[-1] == "done"

    # StructuredEvent must precede DoneEvent.
    structured_idx = next(i for i, e in enumerate(events) if e.type == "structured")
    done_idx = next(i for i, e in enumerate(events) if e.type == "done")
    assert structured_idx < done_idx


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_tool_call_roundtrip(graph, llm_config, user_a, org_a, default_role, db):
    """Stub LLM emits get_flow_overview tool call → service runs it → feeds result back."""
    from tables.services.flow_assistant import FlowAssistantService
    from tables.models.flow_assistant_models import (
        FlowAssistant,
        FlowAssistantConversation,
    )
    from tables.services.llm_clients.base import ToolCallEvent, DoneEvent, TokenEvent
    from asgiref.sync import sync_to_async

    user_message = "Tell me about this flow"

    org_user = await sync_to_async(OrganizationUser.objects.create)(
        user=user_a, org=org_a, role=default_role
    )
    assistant = await sync_to_async(FlowAssistant.objects.create)(
        graph=graph, llm_config=llm_config
    )
    conversation = await sync_to_async(_make_conversation_with_messages)(
        assistant,
        org_user,
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": user_message},
        ],
    )

    call_count = {"tool": 0, "final": 0}

    async def fake_stream_with_tool_call(messages, tools):
        # First call: emit tool call
        if call_count["tool"] == 0:
            call_count["tool"] += 1
            yield ToolCallEvent(id="call_1", name="get_flow_overview", args={})
            yield DoneEvent()
        else:
            # Second call (after tool result): emit final reply
            call_count["final"] += 1
            yield TokenEvent(content="This flow has 0 nodes.")
            yield DoneEvent()

    with patch(
        "tables.services.flow_assistant.service.get_llm_client"
    ) as mock_get_client:
        mock_client = MagicMock()
        mock_client.stream_completion = fake_stream_with_tool_call
        mock_get_client.return_value = mock_client

        service = FlowAssistantService()
        events = []
        async for event in service.stream_reply(conversation, user_message):
            events.append(event)

    # Tool call event must be in the stream
    tool_call_events = [e for e in events if e.type == "tool_call"]
    assert len(tool_call_events) == 1
    assert tool_call_events[0].name == "get_flow_overview"

    # Tool result event must be in the stream
    tool_result_events = [e for e in events if e.type == "tool_result"]
    assert len(tool_result_events) == 1

    # Final reply is plain text → fallback branch emits one StructuredEvent
    # carrying the joined content (no TokenEvents during final turn because
    # the partial-JSON extractor finds no `message` field in the raw text).
    structured_events = [e for e in events if e.type == "structured"]
    assert len(structured_events) == 1
    final_message = structured_events[0].message
    assert (
        "flow" in final_message.lower() or "nodes" in final_message.lower()
    ), f"Expected 'flow' or 'nodes' in final message: {final_message!r}"
    assert structured_events[0].ef_tables == []
    assert structured_events[0].action_message == []

    # Done event last
    assert events[-1].type == "done"

    # Conversation must be persisted with tool messages
    await sync_to_async(conversation.refresh_from_db)()
    messages_snapshot = await sync_to_async(lambda: list(conversation.messages))()
    roles = [m["role"] for m in messages_snapshot]
    assert "tool" in roles
    assert "assistant" in roles


# ── Plain-text (non-JSON) fallback tests ─────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stream_reply_plain_text_emits_structured_event(
    graph, llm_config, user_a, org_a, default_role, db
):
    """Production repro: model ignores response_format and returns multi-chunk plain prose.

    When the LLM emits free-form text (not JSON), the partial-JSON extractor
    produces no deltas, so no TokenEvents reach the frontend during streaming.
    The fallback branch must emit one terminal StructuredEvent carrying the
    fully-joined text so the frontend renders a non-empty bubble.

    This mirrors the exact failure mode seen with the gpt-oss-120b model served
    via a LiteLLM proxy with `drop_params: true` — the proxy silently drops
    `response_format`, the model returns prose, and without the fix the FE shows
    an empty assistant bubble.
    """
    from tables.services.flow_assistant import FlowAssistantService
    from tables.models.flow_assistant_models import FlowAssistant
    from asgiref.sync import sync_to_async

    user_message = "What do you do?"
    plain_text_reply = "This is a plain text reply."

    org_user = await sync_to_async(OrganizationUser.objects.create)(
        user=user_a, org=org_a, role=default_role
    )
    assistant = await sync_to_async(FlowAssistant.objects.create)(
        graph=graph, llm_config=llm_config
    )
    conversation = await sync_to_async(_make_conversation_with_messages)(
        assistant,
        org_user,
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": user_message},
        ],
    )

    # Emit as multiple chunks to mirror real streaming (not a single token).
    chunks = ["This ", "is ", "a ", "plain ", "text ", "reply."]

    async def fake_stream(messages, tools):
        for chunk in chunks:
            yield TokenEvent(content=chunk)
        yield DoneEvent()

    with patch(
        "tables.services.flow_assistant.service.get_llm_client"
    ) as mock_get_client:
        mock_client = MagicMock()
        mock_client.stream_completion = fake_stream
        mock_get_client.return_value = mock_client

        service = FlowAssistantService()
        events = []
        async for event in service.stream_reply(conversation, user_message):
            events.append(event)

    # Exactly one StructuredEvent must carry the assembled plain text.
    structured_events = [e for e in events if e.type == "structured"]
    assert len(structured_events) == 1, (
        f"Expected 1 StructuredEvent, got {len(structured_events)}. "
        f"All event types: {[e.type for e in events]}"
    )
    terminal = structured_events[0]
    assert (
        terminal.message == plain_text_reply
    ), f"Expected message={plain_text_reply!r}, got {terminal.message!r}"
    assert terminal.ef_tables == []
    assert terminal.action_message == []

    # DoneEvent must be the last event.
    assert events[-1].type == "done"

    # StructuredEvent must precede DoneEvent.
    structured_idx = next(i for i, e in enumerate(events) if e.type == "structured")
    done_idx = next(i for i, e in enumerate(events) if e.type == "done")
    assert structured_idx < done_idx

    # The reply must be persisted in the conversation.
    from asgiref.sync import sync_to_async

    await sync_to_async(conversation.refresh_from_db)()
    messages_snapshot = await sync_to_async(lambda: list(conversation.messages))()
    assistant_msgs = [m for m in messages_snapshot if m.get("role") == "assistant"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0]["content"] == plain_text_reply


# ── Rich response format (structured output) tests ───────────────────────────


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_structured_output_event_emitted(
    graph, llm_config, user_a, org_a, default_role, db
):
    """LLM streams JSON tokens → service emits token deltas for `message` field
    plus one StructuredEvent at end-of-stream with the full payload."""
    from tables.services.flow_assistant import FlowAssistantService
    from tables.models.flow_assistant_models import (
        FlowAssistant,
        FlowAssistantConversation,
    )
    from asgiref.sync import sync_to_async

    user_message = "show me the nodes"

    org_user = await sync_to_async(OrganizationUser.objects.create)(
        user=user_a, org=org_a, role=default_role
    )
    assistant = await sync_to_async(FlowAssistant.objects.create)(
        graph=graph, llm_config=llm_config
    )
    conversation = await sync_to_async(_make_conversation_with_messages)(
        assistant,
        org_user,
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": user_message},
        ],
    )

    # Simulate the model streaming JSON character by character.
    json_response = '{"message": "hi", "ef_tables": [], "action_message": []}'
    json_tokens = list(json_response)

    async def fake_stream(messages, tools):
        for char in json_tokens:
            yield TokenEvent(content=char)
        yield DoneEvent()

    with patch(
        "tables.services.flow_assistant.service.get_llm_client"
    ) as mock_get_client:
        mock_client = MagicMock()
        mock_client.stream_completion = fake_stream
        mock_get_client.return_value = mock_client

        service = FlowAssistantService()
        events = []
        async for event in service.stream_reply(conversation, user_message):
            events.append(event)

    # Should have token events carrying the message field delta.
    token_events = [e for e in events if e.type == "token"]
    assert len(token_events) > 0
    full_streamed_text = "".join(e.content for e in token_events)
    assert full_streamed_text == "hi"

    # Should have exactly one StructuredEvent before DoneEvent.
    structured_events = [e for e in events if e.type == "structured"]
    assert len(structured_events) == 1
    structured = structured_events[0]
    assert structured.message == "hi"
    assert structured.ef_tables == []
    assert structured.action_message == []

    # DoneEvent must be last.
    assert events[-1].type == "done"

    # StructuredEvent must come before DoneEvent.
    structured_idx = next(i for i, e in enumerate(events) if e.type == "structured")
    done_idx = next(i for i, e in enumerate(events) if e.type == "done")
    assert structured_idx < done_idx


@pytest.mark.parametrize(
    "buffer, expected",
    [
        # Empty buffer
        ("", ""),
        # Key not yet present
        ('{"messa', ""),
        # Key present, no colon yet
        ('{"message"', ""),
        # Key + colon, no opening quote
        ('{"message": ', ""),
        # Key + opening quote, no content yet
        ('{"message": "', ""),
        # Partial value
        ('{"message": "hi', "hi"),
        # Complete value, no closing brace
        ('{"message": "hi"', "hi"),
        # Complete value in full object
        ('{"message": "hi"}', "hi"),
        # Newline escape
        ('{"message": "hi\\nthere"}', "hi\nthere"),
        # Quote escape
        ('{"message": "with \\"quote\\""}', 'with "quote"'),
        # Backslash escape
        ('{"message": "back\\\\slash"}', "back\\slash"),
        # Value followed by other fields
        ('{"message": "done", "ef_tables": []}', "done"),
        # Empty message value
        ('{"message": ""}', ""),
    ],
)
def test_partial_json_extract_message_field(buffer, expected):
    """Unit tests for the partial-JSON message field extractor."""
    from tables.services.flow_assistant import extract_message_field

    assert extract_message_field(buffer) == expected


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_action_message_persisted(
    graph, llm_config, user_a, org_a, default_role, db
):
    """Structured response with action_message → assistant message in
    conversation.messages retains the action_message field after persist."""
    from tables.services.flow_assistant import FlowAssistantService
    from tables.models.flow_assistant_models import (
        FlowAssistant,
        FlowAssistantConversation,
    )
    from asgiref.sync import sync_to_async

    user_message = "what should I look at next?"

    org_user = await sync_to_async(OrganizationUser.objects.create)(
        user=user_a, org=org_a, role=default_role
    )
    assistant = await sync_to_async(FlowAssistant.objects.create)(
        graph=graph, llm_config=llm_config
    )
    conversation = await sync_to_async(_make_conversation_with_messages)(
        assistant,
        org_user,
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": user_message},
        ],
    )

    action_items = [{"type": "prompt", "text": "Tell me about the nodes"}]
    json_response = (
        '{"message": "Here is a suggestion.", '
        '"ef_tables": [], '
        '"action_message": [{"type": "prompt", "text": "Tell me about the nodes"}]}'
    )

    async def fake_stream(messages, tools):
        yield TokenEvent(content=json_response)
        yield DoneEvent()

    with patch(
        "tables.services.flow_assistant.service.get_llm_client"
    ) as mock_get_client:
        mock_client = MagicMock()
        mock_client.stream_completion = fake_stream
        mock_get_client.return_value = mock_client

        service = FlowAssistantService()
        events = []
        async for event in service.stream_reply(conversation, user_message):
            events.append(event)

    # Verify the assistant message was persisted with action_message field.
    await sync_to_async(conversation.refresh_from_db)()
    messages_snapshot = await sync_to_async(lambda: list(conversation.messages))()
    assistant_msgs = [m for m in messages_snapshot if m.get("role") == "assistant"]
    assert len(assistant_msgs) == 1
    persisted = assistant_msgs[0]
    assert persisted["content"] == "Here is a suggestion."
    assert persisted.get("action_message") == action_items


# ── _messages_for_llm unit tests ─────────────────────────────────────────────


@pytest.mark.django_db
def test_messages_for_llm_evicts_prior_turn_tool_results():
    from tables.services.flow_assistant.helpers import _messages_for_llm

    messages = [
        {"role": "system", "content": "You are..."},
        {"role": "user", "content": "inspect the flow"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_flow_overview", "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "get_flow_overview",
            "content": '{"nodes": [{"id": 1, "name": "start"}, ...long body...]}',
        },
        {"role": "assistant", "content": '{"message": "Found 5 nodes."}'},
        {"role": "user", "content": "tell me about node 1"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {"name": "get_node", "arguments": '{"node_id": 1}'},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_2",
            "name": "get_node",
            "content": '{"id": 1, "config": {...}}',
        },
    ]
    result = _messages_for_llm(messages)
    # Turn 1's tool result is stubbed
    assert result[3]["content"].startswith("[tool result from an earlier turn")
    assert "get_flow_overview" in result[3]["content"]
    assert result[3]["tool_call_id"] == "call_1"  # other fields preserved
    # Turn 2's tool result (current turn) untouched
    assert result[7]["content"] == messages[7]["content"]
    # Non-tool messages untouched
    for i in (0, 1, 2, 4, 5, 6):
        assert result[i] == messages[i]


@pytest.mark.django_db
def test_messages_for_llm_is_idempotent():
    from tables.services.flow_assistant.helpers import _messages_for_llm

    messages = [
        {"role": "system", "content": "..."},
        {"role": "user", "content": "a"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "c",
                    "type": "function",
                    "function": {"name": "get_flow_overview", "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "c",
            "name": "get_flow_overview",
            "content": "<big>",
        },
        {"role": "assistant", "content": "{}"},
        {"role": "user", "content": "b"},
    ]
    once = _messages_for_llm(messages)
    twice = _messages_for_llm(once)
    assert once == twice


@pytest.mark.django_db
def test_messages_for_llm_no_user_message_returns_copy():
    from tables.services.flow_assistant.helpers import _messages_for_llm

    messages = [{"role": "system", "content": "..."}]
    result = _messages_for_llm(messages)
    assert result == messages
    assert result is not messages  # must be a copy


@pytest.mark.django_db
def test_messages_for_llm_truncates_long_args():
    from tables.services.flow_assistant.helpers import _messages_for_llm

    long_args = '{"x": "' + ("a" * 500) + '"}'
    messages = [
        {"role": "system", "content": "..."},
        {"role": "user", "content": "a"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "c",
                    "type": "function",
                    "function": {"name": "load_skill", "arguments": long_args},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c", "name": "load_skill", "content": "<big>"},
        {"role": "assistant", "content": "{}"},
        {"role": "user", "content": "b"},
    ]
    result = _messages_for_llm(messages)
    stub = result[3]["content"]
    assert "…" in stub  # truncation marker present
    assert len(stub) < 500  # stub itself stays small (longer fixed prefix, but bounded)


# ── action_message / ef_tables strip test (Fix: strict-provider compat) ────────


@pytest.mark.django_db
def test_messages_for_llm_strips_fa_internal_fields():
    """_messages_for_llm must remove ef_tables, action_message, and interrupted
    from every message before it is sent to the LLM.

    Root cause of the Fireworks bug: the second turn loaded the persisted
    assistant message (which had action_message set) and forwarded it verbatim.
    Fireworks rejects unknown message fields with a 400 'Extra inputs are not
    permitted' error. OpenAI silently ignores them, masking the bug.

    The fix must:
    - Strip action_message, ef_tables, interrupted from outgoing messages.
    - Preserve the fields in the source dicts (no mutation of the input list).
    - Preserve all LLM-compliant fields (role, content, tool_calls,
      tool_call_id, name).
    """
    from tables.services.flow_assistant.helpers import _messages_for_llm

    action_items = [
        {"type": "prompt", "text": "What do you do?"},
        {"type": "prompt", "text": "Show me recent runs"},
    ]
    ef_tables_data = [{"headers": ["col"], "rows": [["val"]]}]

    messages = [
        {"role": "system", "content": "You are the FA."},
        {"role": "user", "content": "Test"},
        # Persisted assistant message from turn 1 — has FA-internal fields.
        {
            "role": "assistant",
            "content": "Got it.",
            "ef_tables": ef_tables_data,
            "action_message": action_items,
            "interrupted": False,
        },
        # Second user turn — the one that triggers the 400 on strict providers.
        {"role": "user", "content": "What do you do?"},
    ]

    result = _messages_for_llm(messages)

    # FA-internal fields must not appear in any outgoing message.
    _FA_ONLY_FIELDS = {"ef_tables", "action_message", "interrupted"}
    for i, out_msg in enumerate(result):
        for bad_field in _FA_ONLY_FIELDS:
            assert bad_field not in out_msg, (
                f"Field '{bad_field}' must be stripped from message[{i}] "
                f"before sending to the LLM, but it was present: {out_msg}"
            )

    # LLM-compliant fields must be preserved.
    assert result[0]["role"] == "system"
    assert result[0]["content"] == "You are the FA."
    assert result[2]["role"] == "assistant"
    assert result[2]["content"] == "Got it."
    assert result[3]["role"] == "user"
    assert result[3]["content"] == "What do you do?"

    # Source dicts must NOT have been mutated.
    assert "action_message" in messages[2], "Source dict must not be mutated"
    assert "ef_tables" in messages[2], "Source dict must not be mutated"


@pytest.mark.django_db
def test_messages_for_llm_strips_fa_fields_on_all_message_roles():
    """Stripping applies to every role, not just assistant.

    If FA ever stores extra fields on system/user/tool messages those would also
    be stripped — this test documents the whitelist covers all roles.
    """
    from tables.services.flow_assistant.helpers import _messages_for_llm

    messages = [
        # system with a hypothetical future FA field
        {"role": "system", "content": "sys", "ef_tables": []},
        # user with a hypothetical FA field
        {"role": "user", "content": "hello", "action_message": []},
        # assistant with real FA fields
        {
            "role": "assistant",
            "content": "reply",
            "action_message": [{"type": "prompt", "text": "next"}],
            "ef_tables": [],
            "interrupted": False,
        },
        # tool role with LLM-compliant fields — must be preserved
        {
            "role": "tool",
            "tool_call_id": "call_99",
            "name": "get_flow_overview",
            "content": '{"nodes": []}',
        },
        # second user turn — this is the "current" turn boundary
        {"role": "user", "content": "second"},
    ]

    result = _messages_for_llm(messages)

    _FA_ONLY_FIELDS = {"ef_tables", "action_message", "interrupted"}
    for i, out_msg in enumerate(result):
        for bad_field in _FA_ONLY_FIELDS:
            assert (
                bad_field not in out_msg
            ), f"Field '{bad_field}' found in message[{i}]: {out_msg}"

    # LLM-compliant tool fields must survive.
    tool_msg = next(m for m in result if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "call_99"
    assert tool_msg["name"] == "get_flow_overview"
    assert tool_msg["content"] == '{"nodes": []}'


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stream_reply_second_turn_does_not_send_action_message_to_llm(
    graph, llm_config, user_a, org_a, default_role, db
):
    """End-to-end: after turn 1 persists action_message on the assistant row,
    the second turn's call to stream_completion must NOT receive a messages list
    that contains action_message.

    This is the exact repro for the Fireworks 400 'Extra inputs are not
    permitted, field: messages[2].action_message' error.
    """
    import fakeredis
    from asgiref.sync import sync_to_async
    from unittest.mock import call as mock_call

    user_message_1 = "Test"
    user_message_2 = "What do you do?"
    action_items = [
        {"type": "prompt", "text": "What do you do?"},
        {"type": "prompt", "text": "Show me recent runs"},
    ]

    org_user = await sync_to_async(OrganizationUser.objects.create)(
        user=user_a, org=org_a, role=default_role
    )
    assistant = await sync_to_async(FlowAssistant.objects.create)(
        graph=graph, llm_config=llm_config
    )

    # Seed the conversation as it looks AFTER turn 1 has been persisted:
    # system + user1 + assistant-with-action_message + user2.
    conversation = await sync_to_async(_make_conversation_with_messages)(
        assistant,
        org_user,
        [
            {"role": "system", "content": "You are the FA."},
            {"role": "user", "content": user_message_1},
            {
                "role": "assistant",
                "content": "Got it.",
                "action_message": action_items,
            },
            {"role": "user", "content": user_message_2},
        ],
    )

    fake_redis = fakeredis.FakeRedis(decode_responses=False)
    captured_calls: list[list[dict]] = []

    async def fake_stream(messages, tools):
        # Capture the exact messages list sent to the LLM.
        captured_calls.append(list(messages))
        yield TokenEvent(
            content='{"message": "I assist with your flow.", "ef_tables": [], "action_message": []}'
        )
        yield DoneEvent()

    with (
        patch(
            "tables.services.flow_assistant.service.get_llm_client"
        ) as mock_get_client,
        patch(
            "tables.services.flow_assistant.helpers.RedisService",
        ) as MockRedisService,
    ):
        mock_client = MagicMock()
        mock_client.stream_completion = fake_stream
        mock_get_client.return_value = mock_client

        mock_redis_instance = MagicMock()
        mock_redis_instance.redis_client = fake_redis
        MockRedisService.return_value = mock_redis_instance

        service = FlowAssistantService()
        events = []
        async for event in service.stream_reply(conversation, user_message_2):
            events.append(event)

    assert events[-1].type == "done"
    assert len(captured_calls) == 1, "Expected exactly one LLM call for a simple turn"

    sent_messages = captured_calls[0]
    _FA_ONLY_FIELDS = {"ef_tables", "action_message", "interrupted"}
    for i, msg in enumerate(sent_messages):
        for bad_field in _FA_ONLY_FIELDS:
            assert bad_field not in msg, (
                f"FA-internal field '{bad_field}' found in message[{i}] sent to LLM: {msg}\n"
                f"This would cause a 400 'Extra inputs are not permitted' on strict providers "
                f"such as Fireworks."
            )


# ── Tool-call SSE enrichment test ─────────────────────────────────────────────


@pytest.mark.django_db
def test_tool_call_enrichment_helpers(graph, db):
    """resolve_node_display_name returns the node name; returns None for unknown nodes."""
    from tables.models.graph_models import CodeAgentNode
    from tables.services.flow_assistant import (
        build_node_index,
        resolve_node_display_name,
        resolve_subgraph_display_name,
    )

    node = CodeAgentNode.objects.create(
        graph=graph,
        node_name="my_agent_node",
        system_prompt="do stuff",
        stream_handler_code="",
    )

    # Without pre-built index — builds internally
    name = resolve_node_display_name(graph.pk, node.pk)
    assert name == "my_agent_node"

    # With pre-built index
    index = build_node_index(graph.pk)
    name2 = resolve_node_display_name(graph.pk, node.pk, node_index=index)
    assert name2 == "my_agent_node"

    # Unknown node
    assert resolve_node_display_name(graph.pk, 99999) is None

    # Subgraph name helper
    from tables.models.graph_models import SubGraphNode

    subgraph = Graph.objects.create(name="Sub Flow", description="desc")
    sn = SubGraphNode.objects.create(graph=graph, subgraph=subgraph, node_name="sg1")
    assert resolve_subgraph_display_name(graph.pk, sn.pk) == "Sub Flow"
    assert resolve_subgraph_display_name(graph.pk, 99999) is None


# ── Decision-table decision_rules serialization tests ─────────────────────────


@pytest.mark.django_db
def test_get_node_decision_table_includes_decision_rules(graph, db):
    """get_node for a DecisionTableNode must include a human-readable decision_rules list.

    The list must expose rule names, condition expressions, and routing targets
    so the LLM can reason about branching without additional tool calls.
    """
    from tables.models.graph_models import Condition, ConditionGroup, DecisionTableNode
    from tables.services.flow_assistant import get_node

    node = DecisionTableNode.objects.create(
        graph=graph,
        node_name="budget_check",
        default_next_node_id=None,
        next_error_node_id=None,
    )
    # Rule 1: high-value order
    group_high = ConditionGroup.objects.create(
        decision_table_node=node,
        group_name="high_value_order",
        group_type="simple",
        order=0,
        next_node_id=None,
    )
    Condition.objects.create(
        condition_group=group_high,
        condition_name="amount_check",
        order=0,
        condition="amount > 10000",
    )
    # Rule 2: missing budget code
    group_missing = ConditionGroup.objects.create(
        decision_table_node=node,
        group_name="missing_budget_code",
        group_type="simple",
        order=1,
        next_node_id=None,
    )
    Condition.objects.create(
        condition_group=group_missing,
        condition_name="budget_code_absent",
        order=0,
        condition="budget_code == null",
    )

    result = get_node(graph.pk, str(node.pk))

    assert result.get("type") == "decision_table"
    assert (
        "decision_rules" in result
    ), "decision_rules key missing from get_node response"

    rules = result["decision_rules"]
    assert isinstance(rules, list)
    assert len(rules) == 2

    rule_names = [r["rule_name"] for r in rules]
    assert "high_value_order" in rule_names
    assert "missing_budget_code" in rule_names

    # Each rule must carry human-readable condition expressions
    for rule in rules:
        assert "conditions" in rule, f"Rule {rule['rule_name']} missing conditions"
        assert len(rule["conditions"]) >= 1
        cond = rule["conditions"][0]
        assert "name" in cond
        assert "expression" in cond
        # expression must be a non-empty string — not a hash or id
        assert isinstance(cond["expression"], str) and len(cond["expression"]) > 0

    # Spot-check: high_value_order condition expression is readable
    high_rule = next(r for r in rules if r["rule_name"] == "high_value_order")
    assert high_rule["conditions"][0]["expression"] == "amount > 10000"


@pytest.mark.django_db
def test_get_node_classification_decision_table_includes_decision_rules(graph, db):
    """get_node for a ClassificationDecisionTableNode must include decision_rules.

    Each rule must expose its name, expression, route_code, and routing target.
    """
    from tables.models.graph_models import (
        ClassificationConditionGroup,
        ClassificationDecisionTableNode,
    )
    from tables.services.flow_assistant import get_node

    node = ClassificationDecisionTableNode.objects.create(
        graph=graph,
        node_name="sentiment_router",
        default_next_node_id=None,
        next_error_node_id=None,
    )
    ClassificationConditionGroup.objects.create(
        classification_decision_table_node=node,
        group_name="positive_sentiment",
        order=0,
        expression="sentiment_score > 0.7",
        route_code="pos",
        next_node_id=None,
    )
    ClassificationConditionGroup.objects.create(
        classification_decision_table_node=node,
        group_name="negative_sentiment",
        order=1,
        expression="sentiment_score < 0.3",
        route_code="neg",
        next_node_id=None,
    )

    result = get_node(graph.pk, str(node.pk))

    assert result.get("type") == "classification_decision_table"
    assert (
        "decision_rules" in result
    ), "decision_rules key missing from get_node response"

    rules = result["decision_rules"]
    assert isinstance(rules, list)
    assert len(rules) == 2

    rule_names = [r["rule_name"] for r in rules]
    assert "positive_sentiment" in rule_names
    assert "negative_sentiment" in rule_names

    pos_rule = next(r for r in rules if r["rule_name"] == "positive_sentiment")
    assert pos_rule["route_code"] == "pos"
    assert pos_rule["expression"] == "sentiment_score > 0.7"


@pytest.mark.django_db
def test_get_node_non_decision_type_has_no_decision_rules(graph, db):
    """get_node for non-decision nodes must NOT include a decision_rules key."""
    from tables.models.graph_models import CodeAgentNode
    from tables.services.flow_assistant import get_node

    node = CodeAgentNode.objects.create(
        graph=graph,
        node_name="plain_agent",
        system_prompt="do stuff",
        stream_handler_code="",
    )
    result = get_node(graph.pk, str(node.pk))
    assert "decision_rules" not in result


# ── Phase A: subflow recursion tests ──────────────────────────────────────────


@pytest.mark.django_db
def test_get_subflow_includes_subgraph_graph_id(graph, db):
    """get_subflow must return subgraph_graph_id so the LLM can introspect recursively."""
    from tables.models.graph_models import SubGraphNode
    from tables.services.flow_assistant import get_subflow

    subgraph = Graph.objects.create(name="Child Flow", description="Does child things.")
    sn = SubGraphNode.objects.create(
        graph=graph, subgraph=subgraph, node_name="sg_node"
    )

    result = get_subflow(graph.pk, str(sn.pk))

    assert result.get("name") == "Child Flow"
    assert result.get("description") == "Does child things."
    assert (
        "subgraph_graph_id" in result
    ), "subgraph_graph_id missing from get_subflow response"
    assert result["subgraph_graph_id"] == subgraph.pk


@pytest.mark.django_db
def test_get_subflow_accepts_subgraph_node_pk(graph, db):
    """Strict path: passing the SubGraphNode's PK returns the correct subgraph."""
    from tables.models.graph_models import SubGraphNode
    from tables.services.flow_assistant import get_subflow

    subgraph = Graph.objects.create(name="Strict Flow", description="Strict desc.")
    sn = SubGraphNode.objects.create(
        graph=graph, subgraph=subgraph, node_name="strict_sg"
    )

    result = get_subflow(graph.pk, str(sn.pk))

    assert "error" not in result, f"Unexpected error: {result.get('error')}"
    assert result["name"] == "Strict Flow"
    assert result["description"] == "Strict desc."
    assert result["subgraph_graph_id"] == subgraph.pk


@pytest.mark.django_db
def test_get_subflow_falls_back_to_target_graph_id(db):
    """Fallback path: passing the target subgraph's Graph PK still resolves correctly.

    This is the bug scenario from Fix 19: the LLM passes subgraph.pk (the target
    Graph's PK) instead of sn.pk (the SubGraphNode's PK).  The fallback must
    resolve it rather than returning an error.
    """
    from tables.models.graph_models import SubGraphNode
    from tables.services.flow_assistant import get_subflow

    graph_a = Graph.objects.create(name="Parent Flow", description="Has a subflow.")
    graph_b = Graph.objects.create(name="Target Subflow", description="The target.")

    sn = SubGraphNode.objects.create(
        graph=graph_a, subgraph=graph_b, node_name="sg_fallback"
    )

    # The LLM mistakenly passes graph_b.pk instead of sn.pk.
    result = get_subflow(graph_a.pk, str(graph_b.pk))

    assert (
        "error" not in result
    ), f"Fallback failed — expected resolution, got error: {result.get('error')}"
    assert result["name"] == "Target Subflow"
    assert result["description"] == "The target."
    assert result["subgraph_graph_id"] == graph_b.pk


@pytest.mark.django_db
def test_get_subflow_error_message_lists_available_pks(db):
    """When neither interpretation matches, the error message names available SubGraphNode PKs
    and includes the corrective nudge referencing get_flow_overview.
    """
    from tables.models.graph_models import SubGraphNode
    from tables.services.flow_assistant import get_subflow

    graph_parent = Graph.objects.create(name="Parent", description="")
    graph_child = Graph.objects.create(name="Child", description="")

    sn = SubGraphNode.objects.create(
        graph=graph_parent, subgraph=graph_child, node_name="real_sg"
    )

    # Pass a bogus ID that is neither sn.pk nor graph_child.pk.
    bogus_id = sn.pk + graph_child.pk + 9999
    result = get_subflow(graph_parent.pk, str(bogus_id))

    assert "error" in result, "Expected an error dict for a completely unknown id"
    error_text = result["error"]

    # Must name the corrective source tool.
    assert (
        "get_flow_overview" in error_text
    ), f"Error message must reference get_flow_overview; got: {error_text}"
    # Must list the real available SubGraphNode PK so the LLM can self-correct.
    assert (
        str(sn.pk) in error_text
    ), f"Error message must include the real SubGraphNode PK ({sn.pk}); got: {error_text}"


# ── Phase B: session tools tests ──────────────────────────────────────────────


@pytest.mark.django_db
def test_get_recent_sessions_filters_by_graph_id(db):
    """get_recent_sessions must return only sessions for the requested graph."""
    from django.utils import timezone
    from tables.models.session_models import Session
    from tables.services.flow_assistant.tools import get_recent_sessions

    graph_1 = Graph.objects.create(name="Flow One", description="")
    graph_2 = Graph.objects.create(name="Flow Two", description="")

    now = timezone.now()
    for i in range(2):
        Session.objects.create(
            graph=graph_1,
            status=Session.SessionStatus.END,
            status_updated_at=now,
        )
    for i in range(2):
        Session.objects.create(
            graph=graph_2,
            status=Session.SessionStatus.ERROR,
            status_updated_at=now,
        )

    result = get_recent_sessions(graph_1.pk)
    assert "sessions" in result
    sessions = result["sessions"]
    assert len(sessions) == 2, f"Expected 2 sessions for graph_1, got {len(sessions)}"
    for s in sessions:
        # All returned sessions must match the queried graph (verified via DB query below)
        assert s["status"] == Session.SessionStatus.END


@pytest.mark.django_db
def test_get_recent_sessions_caps_limit(db):
    """Passing limit=100 must return at most 25 sessions."""
    from django.utils import timezone
    from tables.models.session_models import Session
    from tables.services.flow_assistant.tools import get_recent_sessions

    graph_big = Graph.objects.create(name="Big Flow", description="")
    now = timezone.now()
    for _ in range(30):
        Session.objects.create(
            graph=graph_big,
            status=Session.SessionStatus.END,
            status_updated_at=now,
        )

    result = get_recent_sessions(graph_big.pk, limit=100)
    assert len(result["sessions"]) <= 25


@pytest.mark.django_db
def test_get_session_detail_rejects_cross_graph_session(db):
    """get_session_detail must return an error when session belongs to a different graph."""
    from django.utils import timezone
    from tables.models.session_models import Session
    from tables.services.flow_assistant.tools import get_session_detail

    graph_a = Graph.objects.create(name="Graph A", description="")
    graph_b = Graph.objects.create(name="Graph B", description="")
    now = timezone.now()

    session = Session.objects.create(
        graph=graph_a,
        status=Session.SessionStatus.END,
        status_updated_at=now,
    )

    result = get_session_detail(graph_b.pk, session.pk)
    assert "error" in result, "Expected error when session belongs to a different graph"
    # No session data must leak
    assert "session_id" not in result
    assert "status" not in result
    assert "node_trace" not in result


@pytest.mark.django_db
def test_get_session_detail_redacts_message_bodies(db):
    """get_session_detail must not include any message body text from session messages."""
    from django.utils import timezone
    from tables.models.session_models import (
        Session,
        AgentSessionMessage,
        TaskSessionMessage,
    )
    from tables.services.flow_assistant.tools import get_session_detail

    SECRET_AGENT_TEXT = "SUPERSECRET_AGENT_THOUGHT_12345"
    SECRET_TASK_RAW = "SUPERSECRET_TASK_OUTPUT_99999"

    graph_c = Graph.objects.create(name="Graph C", description="")
    now = timezone.now()
    session = Session.objects.create(
        graph=graph_c,
        status=Session.SessionStatus.END,
        status_updated_at=now,
    )

    AgentSessionMessage.objects.create(
        session=session,
        node_name="agent_node",
        execution_order=0,
        thought=SECRET_AGENT_TEXT,
        text="some text",
        result="some result",
    )
    TaskSessionMessage.objects.create(
        session=session,
        node_name="task_node",
        execution_order=1,
        raw=SECRET_TASK_RAW,
        name="task",
        description="a task",
        expected_output="output",
    )

    result = get_session_detail(graph_c.pk, session.pk)
    result_str = str(result)

    assert (
        SECRET_AGENT_TEXT not in result_str
    ), "Agent thought body must not appear in detail response"
    assert (
        SECRET_TASK_RAW not in result_str
    ), "Task raw output must not appear in detail response"
    assert "node_trace" in result


@pytest.mark.django_db
def test_get_node_knowledge_sources_metadata_only(graph, db):
    """Agent's knowledge_collection must appear as metadata — no document content."""
    from tables.models.crew_models import Agent
    from tables.models.knowledge_models.collection_models import (
        SourceCollection,
        DocumentMetadata,
    )
    from tables.services.flow_assistant.tools import _resolve_knowledge_metadata

    collection = SourceCollection.objects.create(
        collection_name="test_collection",
        user_id="test_user",
    )
    DocumentMetadata.objects.create(
        file_name="secret_doc.pdf",
        file_type="pdf",
        file_size=1024,
        source_collection=collection,
    )

    metadata = _resolve_knowledge_metadata(collection.pk)
    assert isinstance(metadata, list)
    assert len(metadata) == 1
    entry = metadata[0]
    assert entry["name"] == "test_collection"
    assert entry["document_count"] == 1
    # Must not contain any document content field
    result_str = str(metadata)
    assert "secret_doc" not in result_str
    assert "content" not in result_str


# ── Phase D: Crew summary in get_node ────────────────────────────────────────


@pytest.mark.django_db
def test_get_node_crew_includes_crew_summary(graph, db):
    """get_node for CrewNode must return crew_summary with agents/tasks, no backstory."""
    from tables.models.crew_models import Agent, Crew, Task
    from tables.models.graph_models import CrewNode
    from tables.services.flow_assistant import get_node

    BACKSTORY_TEXT = "TOPSECRET_BACKSTORY_CONTENT_XYZ"

    agent_1 = Agent.objects.create(
        role="Data Analyst",
        goal="Analyse data accurately",
        backstory=BACKSTORY_TEXT,
    )
    agent_2 = Agent.objects.create(
        role="Report Writer",
        goal="Write clear reports",
        backstory="Another backstory that should not leak",
    )
    crew = Crew.objects.create(name="Analytics Crew", description="Runs analytics jobs")
    crew.agents.set([agent_1, agent_2])

    Task.objects.create(
        crew=crew,
        name="data_ingestion",
        instructions="Load the data from the source system",
        expected_output="Clean dataframe",
        order=0,
    )

    crew_node = CrewNode.objects.create(
        graph=graph, node_name="analytics_crew", crew=crew
    )

    result = get_node(graph.pk, str(crew_node.pk))
    assert result.get("type") == "crew"
    assert (
        "crew_summary" in result
    ), "crew_summary missing from CrewNode get_node response"

    summary = result["crew_summary"]
    assert summary is not None
    assert summary["name"] == "Analytics Crew"
    assert summary["agent_count"] == 2
    assert summary["task_count"] == 1

    # Agents list must include role and goal, but NOT backstory.
    agents = summary["agents"]
    assert len(agents) == 2
    agent_roles = [a["role"] for a in agents]
    assert "Data Analyst" in agent_roles
    assert "Report Writer" in agent_roles
    for agent_entry in agents:
        assert (
            "backstory" not in agent_entry
        ), "backstory must not appear in crew_summary agents"

    # Backstory text must not appear anywhere in the result.
    result_str = str(result)
    assert (
        BACKSTORY_TEXT not in result_str
    ), "backstory content must not leak in get_node response"

    # Tasks list must include name and description snippet.
    tasks = summary["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["name"] == "data_ingestion"


# ── system_prompt build smoke test ───────────────────────────────────────────


def test_build_system_prompt_file_load_and_substitution():
    """Smoke test for the file-based system_prompt build path.

    Verifies that:
    (a) build_system_prompt returns a non-empty string,
    (b) the substituted flow name appears in the output,
    (c) the rich-format marker 'ef_tables' appears (proves rich_format.md loaded),
    (d) no literal '${' remains (proves all Template placeholders were substituted),
    (e) 'particular kind of being' appears (proves personality.md loaded),
    (f) '## Operational rules' appears (proves instructions.md loaded with new header).
    """
    from tables.services.flow_assistant.system_prompt import (
        SystemPromptInputs,
        build_system_prompt,
    )

    inputs = SystemPromptInputs(
        flow_name="Smoke Test Flow",
        flow_description="A flow used in automated tests.",
        today_iso="2026-05-18",
        yesterday_iso="2026-05-17",
        tomorrow_iso="2026-05-19",
        node_summary="  - crew: 1\n  - end: 1",
        nodes_section='Nodes in this flow:\n  - id=1 type=crew name="intake"',
        subflow_summary="  (none)",
    )

    result = build_system_prompt(inputs)

    assert isinstance(result, str) and len(result) > 0
    assert "Smoke Test Flow" in result, "substituted flow_name must appear in output"
    assert "ef_tables" in result, "rich_format.md marker 'ef_tables' must be present"
    assert "${" not in result, "all Template placeholders must be substituted"
    assert "flow is your job description" in result, "personality.md must be loaded"
    assert (
        "## Operational rules" in result
    ), "instructions.md must be loaded with new section header"


# ── Phase F (Fix 16): python_code_summary in get_node ────────────────────────


@pytest.mark.django_db
def test_get_node_python_includes_python_code_summary(graph, db):
    """get_node for PythonNode must include python_code_summary with code, entrypoint, libraries."""
    from tables.models.graph_models import PythonNode
    from tables.models.python_models import PythonCode
    from tables.services.flow_assistant import get_node

    python_code = PythonCode.objects.create(
        code=(
            "import requests\n\n"
            "def main(args):\n"
            "    r = requests.get('https://api.openweathermap.org/data/2.5/weather')\n"
            "    return r.json()"
        ),
        entrypoint="main",
        libraries="requests pandas",
    )
    node = PythonNode.objects.create(
        graph=graph,
        node_name="fetch_weather",
        python_code=python_code,
    )

    result = get_node(graph.pk, str(node.pk))

    assert result.get("type") == "python"
    assert (
        "python_code_summary" in result
    ), "python_code_summary missing from PythonNode get_node response"

    summary = result["python_code_summary"]
    assert summary is not None
    assert "openweathermap" in summary["code"], "code body must contain the API URL"
    assert summary["entrypoint"] == "main"
    assert summary["libraries"] == ["requests", "pandas"]


@pytest.mark.django_db
def test_get_node_webhook_trigger_includes_python_code_summary(graph, db):
    """get_node for WebhookTriggerNode must include python_code_summary with code, entrypoint, libraries."""
    from tables.models.graph_models import WebhookTriggerNode
    from tables.models.python_models import PythonCode
    from tables.services.flow_assistant import get_node

    python_code = PythonCode.objects.create(
        code=(
            "import httpx\n\n"
            "def handle(payload):\n"
            "    resp = httpx.post('https://hooks.example.com/notify', json=payload)\n"
            "    return resp.json()"
        ),
        entrypoint="handle",
        libraries="httpx",
    )
    node = WebhookTriggerNode.objects.create(
        graph=graph,
        node_name="webhook_entry",
        python_code=python_code,
    )

    result = get_node(graph.pk, str(node.pk))

    assert result.get("type") == "webhook_trigger"
    assert (
        "python_code_summary" in result
    ), "python_code_summary missing from WebhookTriggerNode get_node response"

    summary = result["python_code_summary"]
    assert summary is not None
    assert (
        "hooks.example.com" in summary["code"]
    ), "code body must contain the webhook URL"
    assert summary["entrypoint"] == "handle"
    assert summary["libraries"] == ["httpx"]


# ── Fix 17: CDT serialization + pre/post python summaries ────────────────────


@pytest.mark.django_db
def test_get_node_classification_decision_table_serializes_cleanly(graph, db):
    """get_node on a CDT with pre/post FK must not raise during JSON serialization.

    Asserts:
    - json.dumps(result, cls=DjangoJSONEncoder) succeeds (no TypeError from FK
      model instances).  The view layer uses DjangoJSONEncoder for datetimes, so
      the test mirrors that encoding path.
    - FK fields (pre_python_code_id etc.) are NOT in result["config"] — relations
      are skipped generically by _node_to_dict's is_relation check.
    """
    import json

    from django.core.serializers.json import DjangoJSONEncoder

    from tables.models.graph_models import ClassificationDecisionTableNode
    from tables.models.python_models import PythonCode
    from tables.services.flow_assistant import get_node

    pre_code = PythonCode.objects.create(
        code="def pre(args):\n    args['pre_called'] = True",
        entrypoint="pre",
        libraries="",
    )
    post_code = PythonCode.objects.create(
        code="def post(args):\n    args['post_called'] = True",
        entrypoint="post",
        libraries="",
    )
    node = ClassificationDecisionTableNode.objects.create(
        graph=graph,
        node_name="cdt_clean",
        pre_python_code=pre_code,
        post_python_code=post_code,
        default_next_node_id=None,
        next_error_node_id=None,
    )

    result = get_node(graph.pk, str(node.pk))

    # Must be JSON-serializable via the same encoder the view uses.
    serialized = json.dumps(result, cls=DjangoJSONEncoder)
    assert serialized  # non-empty

    # FK fields must NOT appear in config (they are relations, skipped generically).
    config = result.get("config", {})
    relation_keys = {
        "pre_python_code",
        "pre_python_code_id",
        "post_python_code",
        "post_python_code_id",
        "default_llm_config",
        "default_llm_config_id",
        "graph",
        "graph_id",
    }
    for key in relation_keys:
        assert key not in config, f"Relation field '{key}' must not appear in config"


@pytest.mark.django_db
def test_get_node_classification_decision_table_includes_pre_post_python_summaries(
    graph, db
):
    """get_node for CDT must include pre/post python_code_summary with correct code bodies.

    Also verifies that when both FKs are None the keys are still present (value is None).
    """
    from tables.models.graph_models import ClassificationDecisionTableNode
    from tables.models.python_models import PythonCode
    from tables.services.flow_assistant import get_node

    pre_code = PythonCode.objects.create(
        code="def pre(args):\n    args['pre_called'] = True",
        entrypoint="pre",
        libraries="",
    )
    post_code = PythonCode.objects.create(
        code="def post(args):\n    args['post_called'] = True",
        entrypoint="post",
        libraries="",
    )
    node = ClassificationDecisionTableNode.objects.create(
        graph=graph,
        node_name="cdt_with_hooks",
        pre_python_code=pre_code,
        post_python_code=post_code,
        default_next_node_id=None,
        next_error_node_id=None,
    )

    result = get_node(graph.pk, str(node.pk))

    assert result.get("type") == "classification_decision_table"

    # Pre-code summary must be present and contain the expected identifier.
    assert "pre_python_code_summary" in result, "pre_python_code_summary key missing"
    pre_summary = result["pre_python_code_summary"]
    assert pre_summary is not None
    assert "pre_called" in pre_summary["code"]

    # Post-code summary must be present and contain the expected identifier.
    assert "post_python_code_summary" in result, "post_python_code_summary key missing"
    post_summary = result["post_python_code_summary"]
    assert post_summary is not None
    assert "post_called" in post_summary["code"]

    # When FKs are None the keys still exist with value None.
    node_no_hooks = ClassificationDecisionTableNode.objects.create(
        graph=graph,
        node_name="cdt_no_hooks",
        pre_python_code=None,
        post_python_code=None,
        default_next_node_id=None,
        next_error_node_id=None,
    )
    result_no_hooks = get_node(graph.pk, str(node_no_hooks.pk))
    assert "pre_python_code_summary" in result_no_hooks
    assert result_no_hooks["pre_python_code_summary"] is None
    assert "post_python_code_summary" in result_no_hooks
    assert result_no_hooks["post_python_code_summary"] is None


# ── Fix 21: run-history introspection tests ───────────────────────────────────


@pytest.mark.django_db
def test_get_session_stats_counts_by_status_and_date_range(db):
    """get_session_stats returns total, by_status, and respects date range filters."""
    from datetime import timedelta

    from django.utils import timezone

    from tables.models.session_models import Session
    from tables.services.flow_assistant.tools import get_session_stats

    graph_stats = Graph.objects.create(name="Stats Flow", description="")
    now = timezone.now()
    older = now - timedelta(days=5)

    # 2 END sessions created "now", 1 ERROR created 5 days ago, 2 ERROR created "now"
    for _ in range(2):
        s = Session(
            graph=graph_stats,
            status=Session.SessionStatus.END,
            status_updated_at=now,
        )
        s.save()
        # Force created_at to "now" (default=timezone.now fires on insert, so no override needed)

    # 2 ERROR sessions created now
    for _ in range(2):
        Session.objects.create(
            graph=graph_stats,
            status=Session.SessionStatus.ERROR,
            status_updated_at=now,
        )

    # 1 ERROR session artificially set to older date
    old_session = Session.objects.create(
        graph=graph_stats,
        status=Session.SessionStatus.ERROR,
        status_updated_at=older,
    )
    Session.objects.filter(pk=old_session.pk).update(created_at=older)

    # All 5 sessions: total should be 5
    result = get_session_stats(graph_stats.pk)
    assert "error" not in result
    assert result["total"] == 5
    assert result["by_status"][Session.SessionStatus.END] == 2
    assert result["by_status"][Session.SessionStatus.ERROR] == 3

    # Since yesterday: should exclude the old_session → 4 total
    yesterday_iso = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    result_since = get_session_stats(graph_stats.pk, since=yesterday_iso)
    assert result_since["total"] == 4
    assert result_since["by_status"].get(Session.SessionStatus.ERROR, 0) == 2

    # Status filter: only ERROR
    result_error = get_session_stats(graph_stats.pk, status=Session.SessionStatus.ERROR)
    assert result_error["total"] == 3
    assert Session.SessionStatus.END not in result_error["by_status"]

    # Echoed timestamps and filter in response
    result_ranged = get_session_stats(
        graph_stats.pk, since=yesterday_iso, status=Session.SessionStatus.END
    )
    assert result_ranged["since"] is not None
    assert result_ranged["status_filter"] == Session.SessionStatus.END


@pytest.mark.django_db
def test_get_session_stats_rejects_bad_iso(db):
    """get_session_stats returns an error dict when since is not a valid ISO 8601 timestamp."""
    from tables.services.flow_assistant.tools import get_session_stats

    graph_bad = Graph.objects.create(name="Bad ISO Flow", description="")

    result = get_session_stats(graph_bad.pk, since="yesterday")
    assert "error" in result
    assert "ISO 8601" in result["error"]
    assert "yesterday" in result["error"]

    result_until = get_session_stats(graph_bad.pk, until="last-week")
    assert "error" in result_until
    assert "ISO 8601" in result_until["error"]


@pytest.mark.django_db
def test_get_recent_sessions_where_filter(db):
    """get_recent_sessions with where={} filters by variable values."""
    from django.utils import timezone

    from tables.models.session_models import Session
    from tables.services.flow_assistant.tools import get_recent_sessions

    graph_where = Graph.objects.create(name="Where Flow", description="")
    now = timezone.now()

    berlin_session = Session.objects.create(
        graph=graph_where,
        status=Session.SessionStatus.END,
        status_updated_at=now,
        variables={"city": "Berlin", "country": "DE"},
    )
    paris_session = Session.objects.create(
        graph=graph_where,
        status=Session.SessionStatus.END,
        status_updated_at=now,
        variables={"city": "Paris", "country": "FR"},
    )

    result = get_recent_sessions(graph_where.pk, where={"city": "Berlin"})
    assert "error" not in result
    sessions = result["sessions"]
    assert len(sessions) == 1, f"Expected 1 Berlin session, got {len(sessions)}"
    assert sessions[0]["id"] == berlin_session.pk

    # Paris filter
    result_paris = get_recent_sessions(graph_where.pk, where={"city": "Paris"})
    assert len(result_paris["sessions"]) == 1
    assert result_paris["sessions"][0]["id"] == paris_session.pk

    # No match
    result_none = get_recent_sessions(graph_where.pk, where={"city": "Tokyo"})
    assert len(result_none["sessions"]) == 0


@pytest.mark.django_db
def test_get_recent_sessions_include_full_variables(db):
    """include_full_variables=True reads full_variables from status_data["variables"],
    NOT from Session.variables. The two are set to different values here to ensure
    the correct (runtime) path is taken."""
    from django.utils import timezone

    from tables.models.session_models import Session
    from tables.services.flow_assistant.tools import get_recent_sessions

    graph_vars = Graph.objects.create(name="Vars Flow", description="")
    now = timezone.now()
    start_vars = {"city": "Amsterdam", "score": None}
    runtime_vars = {"city": "Amsterdam", "score": 99, "nested": {"a": 1}}

    Session.objects.create(
        graph=graph_vars,
        status=Session.SessionStatus.END,
        status_updated_at=now,
        variables=start_vars,
        status_data={"variables": runtime_vars},
    )

    # Without flag: no full_variables key
    result_plain = get_recent_sessions(graph_vars.pk, include_full_variables=False)
    for s in result_plain["sessions"]:
        assert (
            "full_variables" not in s
        ), "full_variables must be absent when flag is False"

    # With flag: full_variables comes from status_data["variables"], not session.variables
    result_full = get_recent_sessions(graph_vars.pk, include_full_variables=True)
    assert len(result_full["sessions"]) == 1
    row = result_full["sessions"][0]
    assert "full_variables" in row, "full_variables must be present when flag is True"
    # Must be the runtime snapshot, not the start snapshot
    assert row["full_variables"] == runtime_vars
    assert row["start_variables"] == start_vars
    # The two must differ to confirm we read the right path
    assert row["full_variables"] != row["start_variables"]


@pytest.mark.django_db
def test_get_recent_sessions_full_variables_reads_status_data(db):
    """full_variables is populated from status_data["variables"] (the runtime state),
    which differs from Session.variables (the start snapshot)."""
    from django.utils import timezone

    from tables.models.session_models import Session
    from tables.services.flow_assistant.tools import get_recent_sessions

    graph = Graph.objects.create(name="Status Data Flow", description="")
    now = timezone.now()

    session = Session.objects.create(
        graph=graph,
        status=Session.SessionStatus.END,
        status_updated_at=now,
        variables={"request": {"city": "Berlin"}, "weather": None},
        status_data={
            "variables": {"request": {"city": "Berlin"}, "weather": {"temp": 22.5}}
        },
    )

    result = get_recent_sessions(graph.pk, include_full_variables=True)
    assert "sessions" in result
    assert len(result["sessions"]) == 1
    row = result["sessions"][0]

    assert (
        row["start_variables"]["weather"] is None
    ), "start_variables must reflect initial snapshot (weather is None)"
    assert row["full_variables"]["weather"] == {
        "temp": 22.5
    }, "full_variables must reflect runtime state from status_data"


@pytest.mark.django_db
def test_get_recent_sessions_full_variables_falls_back_to_variables(db):
    """When status_data has no 'variables' key, full_variables falls back to Session.variables."""
    from django.utils import timezone

    from tables.models.session_models import Session
    from tables.services.flow_assistant.tools import get_recent_sessions

    graph = Graph.objects.create(name="Fallback Flow", description="")
    now = timezone.now()
    start_vars = {"city": "Berlin", "result": "partial"}

    # status_data exists but has no 'variables' key (abnormal termination scenario)
    session = Session.objects.create(
        graph=graph,
        status=Session.SessionStatus.ERROR,
        status_updated_at=now,
        variables=start_vars,
        status_data={"error": "timeout"},
    )

    result = get_recent_sessions(graph.pk, include_full_variables=True)
    assert len(result["sessions"]) == 1
    row = result["sessions"][0]

    assert (
        row["full_variables"] == start_vars
    ), "full_variables must fall back to Session.variables when status_data has no 'variables' key"

    # Also verify the empty dict case (status_data={}, no 'variables' key at all)
    graph2 = Graph.objects.create(name="Fallback Flow Empty", description="")
    Session.objects.create(
        graph=graph2,
        status=Session.SessionStatus.ERROR,
        status_updated_at=now,
        variables=start_vars,
        # status_data defaults to {}, explicitly set for clarity
        status_data={},
    )

    result2 = get_recent_sessions(graph2.pk, include_full_variables=True)
    assert len(result2["sessions"]) == 1
    assert result2["sessions"][0]["full_variables"] == start_vars


@pytest.mark.django_db
def test_get_recent_sessions_date_range(db):
    """get_recent_sessions respects since/until filters."""
    from datetime import timedelta

    from django.utils import timezone

    from tables.models.session_models import Session
    from tables.services.flow_assistant.tools import get_recent_sessions

    graph_date = Graph.objects.create(name="Date Range Flow", description="")
    now = timezone.now()
    old_time = now - timedelta(days=10)

    recent_session = Session.objects.create(
        graph=graph_date,
        status=Session.SessionStatus.END,
        status_updated_at=now,
    )
    old_session = Session.objects.create(
        graph=graph_date,
        status=Session.SessionStatus.END,
        status_updated_at=old_time,
    )
    Session.objects.filter(pk=old_session.pk).update(created_at=old_time)

    since_iso = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = get_recent_sessions(graph_date.pk, since=since_iso, limit=25)
    ids = [s["id"] for s in result["sessions"]]
    assert recent_session.pk in ids
    assert old_session.pk not in ids, "Old session must be excluded by since filter"

    # Bad ISO rejected
    result_bad = get_recent_sessions(graph_date.pk, since="not-a-date")
    assert "error" in result_bad
    assert "ISO 8601" in result_bad["error"]


@pytest.mark.django_db
def test_get_session_messages_returns_trace_content(db):
    """get_session_messages surfaces thought/text/result for agents and raw for tasks."""
    from django.utils import timezone

    from tables.models.session_models import (
        AgentSessionMessage,
        Session,
        TaskSessionMessage,
    )
    from tables.services.flow_assistant.tools import get_session_messages

    graph_msgs = Graph.objects.create(name="Messages Flow", description="")
    now = timezone.now()
    session = Session.objects.create(
        graph=graph_msgs,
        status=Session.SessionStatus.END,
        status_updated_at=now,
    )

    AGENT_THOUGHT = "I concluded the city is Berlin."
    TASK_RAW = "Final output: Berlin confirmed."

    AgentSessionMessage.objects.create(
        session=session,
        node_name="my_agent",
        execution_order=0,
        thought=AGENT_THOUGHT,
        text="some text",
        result="some result",
    )
    TaskSessionMessage.objects.create(
        session=session,
        node_name="my_task",
        execution_order=1,
        raw=TASK_RAW,
        name="task_1",
        description="a task description",
        expected_output="something",
    )

    result = get_session_messages(graph_msgs.pk, session.pk)
    assert "error" not in result, f"Unexpected error: {result.get('error')}"
    assert result["session_id"] == session.pk
    messages = result["messages"]
    assert len(messages) == 2

    # Sort by execution_order to assert in order
    messages_sorted = sorted(messages, key=lambda m: m["execution_order"])

    agent_msg = messages_sorted[0]
    assert agent_msg["kind"] == "agent"
    assert agent_msg["node_name"] == "my_agent"
    assert agent_msg["content"] == AGENT_THOUGHT

    task_msg = messages_sorted[1]
    assert task_msg["kind"] == "task"
    assert task_msg["node_name"] == "my_task"
    assert task_msg["content"] == TASK_RAW


@pytest.mark.django_db
def test_get_session_messages_rejects_cross_graph_session(db):
    """get_session_messages returns an error when session belongs to a different graph."""
    from django.utils import timezone

    from tables.models.session_models import Session
    from tables.services.flow_assistant.tools import get_session_messages

    graph_a = Graph.objects.create(name="Graph A", description="")
    graph_b = Graph.objects.create(name="Graph B", description="")
    now = timezone.now()

    session = Session.objects.create(
        graph=graph_a,
        status=Session.SessionStatus.END,
        status_updated_at=now,
    )

    result = get_session_messages(graph_b.pk, session.pk)
    assert "error" in result
    assert "different flow" in result["error"] or "not found" in result["error"].lower()
    assert "messages" not in result


@pytest.mark.django_db
def test_get_session_messages_respects_limit_clamp(db):
    """get_session_messages clamps limit to 200; passing 500 returns at most 200."""
    from django.utils import timezone

    from tables.models.session_models import AgentSessionMessage, Session
    from tables.services.flow_assistant.tools import get_session_messages

    graph_limit = Graph.objects.create(name="Limit Flow", description="")
    now = timezone.now()
    session = Session.objects.create(
        graph=graph_limit,
        status=Session.SessionStatus.END,
        status_updated_at=now,
    )

    # Create 220 agent messages
    AgentSessionMessage.objects.bulk_create(
        [
            AgentSessionMessage(
                session=session,
                node_name="agent",
                execution_order=i,
                thought=f"thought {i}",
                text="",
                result="",
            )
            for i in range(220)
        ]
    )

    result = get_session_messages(graph_limit.pk, session.pk, limit=500)
    assert "error" not in result
    assert (
        result["count"] <= 200
    ), f"Expected at most 200 messages, got {result['count']}"


# ── Fix 22: runtime variable path in get_session_detail ──────────────────────


@pytest.mark.django_db
def test_get_session_detail_includes_final_variables_from_status_data(db):
    """get_session_detail must expose final_variables from status_data["variables"],
    not from Session.variables, when the runtime snapshot is available."""
    from django.utils import timezone

    from tables.models.session_models import Session
    from tables.services.flow_assistant.tools import get_session_detail

    graph = Graph.objects.create(name="Detail Vars Flow", description="")
    now = timezone.now()
    start_vars = {"city": "Berlin", "temperature": None, "recommendation": None}
    runtime_vars = {
        "city": "Berlin",
        "temperature": 22.5,
        "recommendation": {"message": "Wear light clothes"},
    }

    session = Session.objects.create(
        graph=graph,
        status=Session.SessionStatus.END,
        status_updated_at=now,
        variables=start_vars,
        status_data={"variables": runtime_vars},
    )

    result = get_session_detail(graph.pk, session.pk)

    assert "error" not in result, f"Unexpected error: {result.get('error')}"
    assert (
        "final_variables" in result
    ), "final_variables key must be present in get_session_detail"

    final = result["final_variables"]
    assert (
        final["temperature"] == 22.5
    ), "final_variables must reflect runtime state from status_data (temperature was null at start)"
    assert final["recommendation"] == {
        "message": "Wear light clothes"
    }, "final_variables must include output variables populated by the flow"


@pytest.mark.django_db
def test_get_session_detail_final_variables_falls_back_to_variables(db):
    """When status_data has no 'variables' key, final_variables falls back to Session.variables."""
    from django.utils import timezone

    from tables.models.session_models import Session
    from tables.services.flow_assistant.tools import get_session_detail

    graph = Graph.objects.create(name="Detail Fallback Flow", description="")
    now = timezone.now()
    start_vars = {"city": "Paris", "result": None}

    # No 'variables' key in status_data (abnormal termination)
    session_no_vars_key = Session.objects.create(
        graph=graph,
        status=Session.SessionStatus.ERROR,
        status_updated_at=now,
        variables=start_vars,
        status_data={"error": "agent timed out"},
    )

    result = get_session_detail(graph.pk, session_no_vars_key.pk)
    assert "error" not in result
    assert (
        result["final_variables"] == start_vars
    ), "final_variables must fall back to Session.variables when status_data has no 'variables' key"

    # status_data is empty dict (default, no 'variables' key)
    session_empty_status_data = Session.objects.create(
        graph=graph,
        status=Session.SessionStatus.ERROR,
        status_updated_at=now,
        variables=start_vars,
        status_data={},
    )

    result2 = get_session_detail(graph.pk, session_empty_status_data.pk)
    assert "error" not in result2
    assert (
        result2["final_variables"] == start_vars
    ), "final_variables must fall back to Session.variables when status_data is an empty dict"


# ── Fix 23: Cancel mechanism tests ───────────────────────────────────────────


@pytest.mark.django_db
def test_cancel_endpoint_sets_redis_flag(
    graph, flow_assistant, conversation_a, auth_client_a
):
    """POST /cancel/ sets the fa:cancel:<conv_id> key in Redis."""
    import fakeredis
    from unittest.mock import patch

    fake_redis = fakeredis.FakeRedis(decode_responses=False)

    with patch(
        "tables.services.flow_assistant.helpers.RedisService",
    ) as MockRedisService:
        mock_instance = MagicMock()
        mock_instance.redis_client = fake_redis
        MockRedisService.return_value = mock_instance

        url = reverse(
            "flow-assistant-cancel",
            kwargs={
                "graph_id": graph.pk,
                "conversation_id": conversation_a.pk,
            },
        )
        response = auth_client_a.post(url)

    assert response.status_code == 202, response.content
    assert response.data == {"cancelled": True}
    # The cancel flag must be present in fakeredis
    expected_key = f"fa:cancel:{conversation_a.pk}".encode()
    assert fake_redis.get(expected_key) == b"1"


@pytest.mark.django_db
def test_cancel_endpoint_org_scoped(
    graph, flow_assistant, conversation_a, auth_client_b
):
    """User from a different org cannot cancel another user's conversation — returns 404."""
    url = reverse(
        "flow-assistant-cancel",
        kwargs={
            "graph_id": graph.pk,
            "conversation_id": conversation_a.pk,
        },
    )
    # auth_client_b belongs to org_a but is a different user; conversation_a
    # is owned by org_user_a, so org_user_b's resolution will return no match.
    response = auth_client_b.post(url)
    assert response.status_code == 404, response.content


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stream_reply_bails_on_cancel_flag(
    graph, llm_config, user_a, org_a, default_role, db
):
    """stream_reply stops early and persists an interrupted partial when the cancel
    flag is set before the LLM call completes."""
    import asyncio
    import fakeredis
    from unittest.mock import patch
    from asgiref.sync import sync_to_async
    from tables.services.flow_assistant import FlowAssistantService
    from tables.services.flow_assistant.constants import _CANCEL_KEY
    from tables.models.flow_assistant_models import (
        FlowAssistant,
        FlowAssistantConversation,
    )

    user_message = "what does this flow do?"

    org_user = await sync_to_async(OrganizationUser.objects.create)(
        user=user_a, org=org_a, role=default_role
    )
    assistant = await sync_to_async(FlowAssistant.objects.create)(
        graph=graph, llm_config=llm_config
    )
    conversation = await sync_to_async(_make_conversation_with_messages)(
        assistant,
        org_user,
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": user_message},
        ],
    )

    fake_redis = fakeredis.FakeRedis(decode_responses=False)
    cancel_key = _CANCEL_KEY.format(conv_id=conversation.pk).encode()

    async def fake_stream(messages, tools):
        # Yield the first token, then set the cancel flag so it is seen by the
        # inner-loop checkpoint on the very next iteration.
        yield TokenEvent(content="partial ")
        fake_redis.set(cancel_key, b"1", ex=300)
        yield TokenEvent(content="answer")
        yield DoneEvent()

    with (
        patch(
            "tables.services.flow_assistant.service.get_llm_client"
        ) as mock_get_client,
        patch(
            "tables.services.flow_assistant.helpers.RedisService",
        ) as MockRedisService,
    ):
        mock_client = MagicMock()
        mock_client.stream_completion = fake_stream
        mock_get_client.return_value = mock_client

        mock_redis_instance = MagicMock()
        mock_redis_instance.redis_client = fake_redis
        MockRedisService.return_value = mock_redis_instance

        service = FlowAssistantService()
        events = []
        async for event in service.stream_reply(conversation, user_message):
            events.append(event)

    # The last event must be a DoneEvent with interrupted=True.
    assert events, "No events were yielded"
    last = events[-1]
    assert last.type == "done"
    assert last.interrupted is True

    # The cancel flag must have been cleared.
    assert fake_redis.get(cancel_key) is None

    # The conversation must be persisted with a partial assistant entry.
    await sync_to_async(conversation.refresh_from_db)()
    messages_snapshot = await sync_to_async(lambda: list(conversation.messages))()
    assistant_msgs = [m for m in messages_snapshot if m.get("role") == "assistant"]
    assert len(assistant_msgs) >= 1
    partial = assistant_msgs[-1]
    assert partial.get("interrupted") is True


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stream_reply_disconnect_persists_partial(
    graph, llm_config, user_a, org_a, default_role, db
):
    """When the LLM stream raises asyncio.CancelledError (simulated disconnect),
    the finally block persists a partial assistant message with interrupted=True."""
    import asyncio
    import fakeredis
    from unittest.mock import patch
    from asgiref.sync import sync_to_async
    from tables.services.flow_assistant import FlowAssistantService
    from tables.models.flow_assistant_models import (
        FlowAssistant,
        FlowAssistantConversation,
    )

    user_message = "hello"

    org_user = await sync_to_async(OrganizationUser.objects.create)(
        user=user_a, org=org_a, role=default_role
    )
    assistant = await sync_to_async(FlowAssistant.objects.create)(
        graph=graph, llm_config=llm_config
    )
    conversation = await sync_to_async(_make_conversation_with_messages)(
        assistant,
        org_user,
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": user_message},
        ],
    )

    fake_redis = fakeredis.FakeRedis(decode_responses=False)

    async def fake_stream_then_cancel(messages, tools):
        yield TokenEvent(content="hello ")
        yield TokenEvent(content="world")
        raise asyncio.CancelledError("simulated disconnect")

    with (
        patch(
            "tables.services.flow_assistant.service.get_llm_client"
        ) as mock_get_client,
        patch(
            "tables.services.flow_assistant.helpers.RedisService",
        ) as MockRedisService,
    ):
        mock_client = MagicMock()
        mock_client.stream_completion = fake_stream_then_cancel
        mock_get_client.return_value = mock_client

        mock_redis_instance = MagicMock()
        mock_redis_instance.redis_client = fake_redis
        MockRedisService.return_value = mock_redis_instance

        service = FlowAssistantService()
        # CancelledError propagates out of the generator after the finally block runs.
        with pytest.raises(asyncio.CancelledError):
            async for _event in service.stream_reply(conversation, user_message):
                pass

    # Despite the exception, the finally block must have persisted the partial.
    await sync_to_async(conversation.refresh_from_db)()
    messages_snapshot = await sync_to_async(lambda: list(conversation.messages))()
    assistant_msgs = [m for m in messages_snapshot if m.get("role") == "assistant"]
    assert len(assistant_msgs) >= 1, "No assistant message persisted on disconnect"
    partial = assistant_msgs[-1]
    assert partial.get("interrupted") is True
    # The partial content should contain whatever tokens were streamed.
    assert "hello" in partial.get("content", "")


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_reasoning_empty_and_no_tool_injects_hint(
    graph, llm_config, user_a, org_a, default_role, db
):
    """Reasoning model exhausted budget on reasoning, no final content → hint emitted and NOT persisted."""
    import fakeredis
    from asgiref.sync import sync_to_async

    user_message = "summarize this flow"

    org_user = await sync_to_async(OrganizationUser.objects.create)(
        user=user_a, org=org_a, role=default_role
    )
    assistant = await sync_to_async(FlowAssistant.objects.create)(
        graph=graph, llm_config=llm_config
    )
    conversation = await sync_to_async(_make_conversation_with_messages)(
        assistant,
        org_user,
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": user_message},
        ],
    )

    fake_redis = fakeredis.FakeRedis(decode_responses=False)

    async def fake_stream(messages, tools):
        # Model only reasoned: no content tokens, no tool calls.
        yield DoneEvent(reasoning_observed=True)

    with (
        patch(
            "tables.services.flow_assistant.service.get_llm_client"
        ) as mock_get_client,
        patch(
            "tables.services.flow_assistant.helpers.RedisService",
        ) as MockRedisService,
    ):
        mock_client = MagicMock()
        mock_client.stream_completion = fake_stream
        mock_get_client.return_value = mock_client

        mock_redis_instance = MagicMock()
        mock_redis_instance.redis_client = fake_redis
        MockRedisService.return_value = mock_redis_instance

        service = FlowAssistantService()
        events = []
        async for event in service.stream_reply(conversation, user_message):
            events.append(event)

    # Hint must appear in the streamed token output.
    hint_substring = "increasing `max_tokens`"
    token_contents = [e.content for e in events if e.type == "token"]
    assert any(
        hint_substring in c for c in token_contents
    ), f"Expected hint substring in streamed tokens, got: {token_contents}"

    # Hint must NOT be persisted to conversation history.
    refreshed = await sync_to_async(FlowAssistantConversation.objects.get)(
        pk=conversation.pk
    )
    persisted_messages = await sync_to_async(lambda: list(refreshed.messages))()
    for msg in persisted_messages:
        assert hint_substring not in (
            msg.get("content") or ""
        ), f"Hint leaked into persisted history: {msg}"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_reasoning_with_content_does_not_inject_hint(
    graph, llm_config, user_a, org_a, default_role, db
):
    """Model reasoned AND produced final content → hint must NOT appear."""
    import fakeredis
    from asgiref.sync import sync_to_async

    user_message = "hi"

    org_user = await sync_to_async(OrganizationUser.objects.create)(
        user=user_a, org=org_a, role=default_role
    )
    assistant = await sync_to_async(FlowAssistant.objects.create)(
        graph=graph, llm_config=llm_config
    )
    conversation = await sync_to_async(_make_conversation_with_messages)(
        assistant,
        org_user,
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": user_message},
        ],
    )

    async def fake_stream(messages, tools):
        yield TokenEvent(content="hello")
        yield DoneEvent(reasoning_observed=True)

    fake_redis = fakeredis.FakeRedis(decode_responses=False)

    with (
        patch(
            "tables.services.flow_assistant.service.get_llm_client"
        ) as mock_get_client,
        patch(
            "tables.services.flow_assistant.helpers.RedisService",
        ) as MockRedisService,
    ):
        mock_client = MagicMock()
        mock_client.stream_completion = fake_stream
        mock_get_client.return_value = mock_client

        mock_redis_instance = MagicMock()
        mock_redis_instance.redis_client = fake_redis
        MockRedisService.return_value = mock_redis_instance

        service = FlowAssistantService()
        events = []
        async for event in service.stream_reply(conversation, user_message):
            events.append(event)

    hint_substring = "increasing `max_tokens`"
    token_contents = [e.content for e in events if e.type == "token"]
    assert not any(
        hint_substring in c for c in token_contents
    ), f"Hint should have been suppressed when content was produced: {token_contents}"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_reasoning_with_tool_call_does_not_inject_hint(
    graph, llm_config, user_a, org_a, default_role, db
):
    """Model reasoned then called a tool → tool call IS the productive output → no hint."""
    import fakeredis
    from asgiref.sync import sync_to_async

    user_message = "what nodes are in this flow?"

    org_user = await sync_to_async(OrganizationUser.objects.create)(
        user=user_a, org=org_a, role=default_role
    )
    assistant = await sync_to_async(FlowAssistant.objects.create)(
        graph=graph, llm_config=llm_config
    )
    conversation = await sync_to_async(_make_conversation_with_messages)(
        assistant,
        org_user,
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": user_message},
        ],
    )

    call_count = {"n": 0}

    async def fake_stream(messages, tools):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First iteration: model reasoned and called a tool.
            yield ToolCallEvent(id="call_1", name="get_flow_overview", args={})
            yield DoneEvent(reasoning_observed=True)
        else:
            # Second iteration: model produces final answer using tool result.
            yield TokenEvent(content="Flow has 0 nodes.")
            yield DoneEvent(reasoning_observed=False)

    fake_redis = fakeredis.FakeRedis(decode_responses=False)

    with (
        patch(
            "tables.services.flow_assistant.service.get_llm_client"
        ) as mock_get_client,
        patch(
            "tables.services.flow_assistant.helpers.RedisService",
        ) as MockRedisService,
    ):
        mock_client = MagicMock()
        mock_client.stream_completion = fake_stream
        mock_get_client.return_value = mock_client

        mock_redis_instance = MagicMock()
        mock_redis_instance.redis_client = fake_redis
        MockRedisService.return_value = mock_redis_instance

        service = FlowAssistantService()
        events = []
        async for event in service.stream_reply(conversation, user_message):
            events.append(event)

    hint_substring = "increasing `max_tokens`"
    token_contents = [e.content for e in events if e.type == "token"]
    assert not any(
        hint_substring in c for c in token_contents
    ), f"Hint should have been suppressed when a tool was called: {token_contents}"
