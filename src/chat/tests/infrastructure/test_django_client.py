import asyncio
import json

import httpx

import pytest
from application.ports import OPERATOR_NAME_MAX_LENGTH, CallerCredentials
from domain.errors import FlowForbiddenError, FlowNotFoundError, FlowStartError, InvalidTokenError, NotMemberError, RunNotFoundError, UpstreamUnavailableError
from infrastructure.django.client import DjangoClient
from tests.fake_django import FakeDjango

CHAT_FLOW = {"org_id": 1, "start_variables": {"variables": {"chat_history": [], "user_message": ""}}, "output_map": {"reply": "variables.reply"}}


@pytest.fixture
def django():
    return FakeDjango()


@pytest.fixture
async def client(settings, django):
    client = DjangoClient(settings, transport=django.transport)
    yield client
    await client.aclose()


async def test_start_run_sends_system_key_and_callback(client, django):
    django.graphs[5] = CHAT_FLOW
    session_id = await client.start_run(org_id=1, graph_id=5, variables={"user_message": "hi", "chat_history": []}, token_budget=500, callback_url="http://chat:8200/cb", callback_secret="s" * 43)
    request = django.requests[-1]
    body = json.loads(request.content)
    assert session_id == 100
    assert request.headers["X-Api-Key"] == settings_key(client)
    assert request.headers["Host"] == "localhost"
    assert body == {"graph_id": 5, "variables": {"user_message": "hi", "chat_history": []}, "token_budget": 500, "callback_url": "http://chat:8200/cb", "callback_secret": "s" * 43}


def settings_key(client: DjangoClient) -> str:
    return client._system_headers["X-Api-Key"]


async def test_malformed_2xx_body_is_upstream_unavailable(client, django):
    django.graphs[5] = CHAT_FLOW
    django.run_session_response = (201, {})
    with pytest.raises(UpstreamUnavailableError):
        await client.start_run(org_id=1, graph_id=5, variables={}, token_budget=1, callback_url="u", callback_secret="s" * 43)


async def test_start_run_404_is_flow_not_found(client, django):
    with pytest.raises(FlowNotFoundError):
        await client.start_run(org_id=1, graph_id=9, variables={}, token_budget=1, callback_url="u", callback_secret="s" * 43)


async def test_start_run_other_error_is_flow_start_error(client, django):
    django.run_session_response = (400, {"error": "no entry point"})
    with pytest.raises(FlowStartError, match="no entry point"):
        await client.start_run(org_id=1, graph_id=5, variables={}, token_budget=1, callback_url="u", callback_secret="s" * 43)


async def test_stop_run_ignores_unknown_session(client, django):
    django.sessions[7] = {"org_id": 1, "status": "run", "token_usage": {}}
    await client.stop_run(7)
    await client.stop_run(8)
    assert django.stopped == [7]


async def test_run_status_and_result_use_org_header(client, django):
    django.sessions[7] = {"org_id": 1, "status": "end", "token_usage": {"total_tokens": 3}}
    django.messages[7] = [
        {"id": 1, "message_data": {"message_type": "agent", "x": 1}},
        {"id": 2, "message_data": {"message_type": "graph_end", "end_node_result": {"reply": "hi"}}},
    ]
    status = await client.run_status(org_id=1, session_id=7)
    result = await client.run_result(org_id=1, session_id=7)
    assert (status.status, status.token_usage) == ("end", {"total_tokens": 3})
    assert result == {"reply": "hi"}
    assert django.requests[-1].headers["X-Organization-Id"] == "1"
    with pytest.raises(RunNotFoundError):
        await client.run_status(org_id=2, session_id=7)
    assert await client.run_result(org_id=2, session_id=7) is None


ACTIVE = {"active": True, "user_id": 4, "email": "a@b", "scopes": [], "is_superadmin": False}


@pytest.fixture
def reader(django):
    """jwt-reader may read flows in org 1 and org 2; jwt-chats-only has every chats action in org 1 but no flows:read."""
    django.users["jwt-reader"] = {**ACTIVE, "org_ids": [1, 2]}
    django.users["jwt-chats-only"] = {**ACTIVE, "org_ids": [1]}
    django.permissions[("jwt-reader", 1)] = {"chats": ["create"], "flows": ["read"]}
    django.permissions[("jwt-reader", 2)] = {"chats": ["create"], "flows": ["read"]}
    django.permissions[("jwt-chats-only", 1)] = {"chats": ["create", "read", "update", "delete", "use"]}
    return CallerCredentials(org_id=1, bearer_token="jwt-reader")


async def test_graph_contract_is_read_with_the_callers_token_and_org(client, django, reader):
    django.graphs[5] = CHAT_FLOW
    contract = await client.graph_contract(reader, graph_id=5)
    assert contract.start_variables == {"chat_history": [], "user_message": ""}
    assert contract.output_map == {"reply": "variables.reply"}
    headers = django.requests[-1].headers
    assert headers["Authorization"] == "Bearer jwt-reader" and headers["X-Organization-Id"] == "1"
    assert "X-Api-Key" not in headers


async def test_graph_contract_for_another_orgs_graph_is_not_found(client, django, reader):
    django.graphs[5] = CHAT_FLOW
    with pytest.raises(FlowNotFoundError):
        await client.graph_contract(CallerCredentials(org_id=2, bearer_token="jwt-reader"), graph_id=5)


async def test_graph_contract_without_flows_read_is_forbidden_whether_or_not_the_graph_exists(client, django, reader):
    django.graphs[5] = CHAT_FLOW
    for graph_id in (5, 999):
        with pytest.raises(FlowForbiddenError):
            await client.graph_contract(CallerCredentials(org_id=1, bearer_token="jwt-chats-only"), graph_id=graph_id)


async def test_graph_contract_with_a_rejected_token_is_invalid_token(client, django):
    django.graphs[5] = CHAT_FLOW
    with pytest.raises(InvalidTokenError):
        await client.graph_contract(CallerCredentials(org_id=1, bearer_token="expired"), graph_id=5)


def test_caller_credentials_hide_the_token_in_repr():
    assert "jwt-reader" not in repr(CallerCredentials(org_id=1, bearer_token="jwt-reader"))


async def test_run_calls_use_the_system_key_not_a_user_token(client, django):
    django.graphs[5] = CHAT_FLOW
    session_id = await client.start_run(org_id=1, graph_id=5, variables={}, token_budget=1, callback_url="u", callback_secret="s" * 43)
    await client.run_status(org_id=1, session_id=session_id)
    await client.run_result(org_id=1, session_id=session_id)
    await client.stop_run(session_id)
    for request in django.requests:
        assert request.headers["X-Api-Key"] == settings_key(client) and "Authorization" not in request.headers


async def test_graph_without_nodes(client, django, reader):
    django.graphs[6] = {"org_id": 1, "start_variables": None, "output_map": None}
    contract = await client.graph_contract(reader, graph_id=6)
    assert (contract.start_variables, contract.output_map) == (None, None)


async def test_introspect_and_permissions(client, django):
    django.users["jwt-1"] = {"active": True, "user_id": 4, "email": "a@b", "scopes": [], "org_ids": [1, 2], "is_superadmin": False}
    django.permissions[("jwt-1", 1)] = {"chats": ["read", "use"], "flows": ["read"]}
    django.permissions[("jwt-1", 2)] = "*"
    user = await client.introspect("jwt-1")
    assert (user.user_id, user.org_ids, user.is_superadmin) == (4, [1, 2], False)
    assert await client.introspect("nope") is None
    assert await client.chats_actions("jwt-1", 1) == {"read", "use"}
    assert await client.chats_actions("jwt-1", 2) == {"create", "read", "update", "delete", "use"}
    assert "X-Api-Key" not in django.requests[-1].headers
    with pytest.raises(NotMemberError):
        await client.chats_actions("jwt-1", 3)


async def test_introspect_reads_the_display_name(client, django):
    django.users["jwt-1"] = {"active": True, "user_id": 4, "email": "ada@example.com", "display_name": "  Ada Lovelace ", "scopes": [], "org_ids": [1], "is_superadmin": False}
    assert (await client.introspect("jwt-1")).display_name == "Ada Lovelace"


async def test_introspect_from_an_epicstaff_without_display_names_parses_to_none(client, django):
    django.introspect_omits_display_name = True
    django.users["jwt-1"] = {"active": True, "user_id": 4, "email": "ada@example.com", "scopes": [], "org_ids": [1], "is_superadmin": False}
    user = await client.introspect("jwt-1")
    assert (user.user_id, user.org_ids, user.display_name) == (4, [1], None)
    assert "display_name" not in django.handle(django.requests[-1]).json()  # the key really was missing


@pytest.mark.parametrize("value", [None, "", "   ", 7, ["Ada"]], ids=["null", "empty", "blank", "number", "list"])
async def test_introspect_with_an_unusable_display_name_parses_to_none(client, django, value):
    django.users["jwt-1"] = {"active": True, "user_id": 4, "email": "ada@example.com", "display_name": value, "scopes": [], "org_ids": [1], "is_superadmin": False}
    assert (await client.introspect("jwt-1")).display_name is None


async def test_introspect_cuts_a_display_name_to_the_stored_length(client, django):
    django.users["jwt-1"] = {"active": True, "user_id": 4, "email": "ada@example.com", "display_name": "A" * 300, "scopes": [], "org_ids": [1], "is_superadmin": False}
    assert (await client.introspect("jwt-1")).display_name == "A" * OPERATOR_NAME_MAX_LENGTH


async def test_transport_error_is_upstream_unavailable(settings):
    def refuse(request):
        raise httpx.ConnectError("refused")

    client = DjangoClient(settings, transport=httpx.MockTransport(refuse))
    with pytest.raises(UpstreamUnavailableError, match="ConnectError"):
        await client.run_status(org_id=1, session_id=7)
    await client.aclose()


async def test_decoding_error_is_upstream_unavailable(settings):
    def corrupt(request):
        raise httpx.DecodingError("bad gzip")

    client = DjangoClient(settings, transport=httpx.MockTransport(corrupt))
    with pytest.raises(UpstreamUnavailableError, match="DecodingError"):
        await client.run_status(org_id=1, session_id=7)
    await client.aclose()


async def test_server_errors_are_upstream_unavailable(settings):
    client = DjangoClient(settings, transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    with pytest.raises(UpstreamUnavailableError, match="503"):
        await client.run_status(org_id=1, session_id=7)
    with pytest.raises(UpstreamUnavailableError):
        await client.introspect("jwt")
    with pytest.raises(UpstreamUnavailableError):
        await client.stop_run(7)
    await client.aclose()


async def test_run_result_finds_graph_end_on_a_later_page(client, django):
    django.sessions[7] = {"org_id": 1, "status": "end", "token_usage": {}}
    django.messages[7] = [{"id": i, "message_data": {"message_type": "agent"}} for i in range(200)]
    django.messages[7].append({"id": 200, "message_data": {"message_type": "graph_end", "end_node_result": {"reply": "late"}}})
    assert await client.run_result(org_id=1, session_id=7) == {"reply": "late"}


async def test_run_result_gives_up_when_the_server_ignores_offset(settings):
    page = {"next": "more", "results": [{"message_data": {"message_type": "agent"}}]}
    client = DjangoClient(settings, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=page)))
    assert await client.run_result(org_id=1, session_id=7) is None
    await client.aclose()


async def test_a_call_slower_than_the_timeout_overall_is_upstream_unavailable(settings):
    # Each httpx phase stays under its own timeout; only the overall deadline catches this.
    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(201, json={"session_id": 1})

    client = DjangoClient(settings.model_copy(update={"CHAT_DJANGO_TIMEOUT": 0.05}), transport=httpx.MockTransport(slow))
    with pytest.raises(UpstreamUnavailableError, match="TimeoutError"):
        await client.start_run(org_id=1, graph_id=5, variables={}, token_budget=1, callback_url="u", callback_secret="s" * 43)
    await client.aclose()


async def _status_request(settings) -> httpx.Request:
    seen = []

    def record(request):
        seen.append(request)
        return httpx.Response(200, json={"status": "end"})

    client = DjangoClient(settings, transport=httpx.MockTransport(record))
    await client.run_status(org_id=1, session_id=7)
    await client.aclose()
    return seen[0]


async def test_without_a_host_header_override_the_url_host_is_sent(settings):
    request = await _status_request(settings.model_copy(update={"CHAT_DJANGO_URL": "https://epicstaff.example.com", "CHAT_DJANGO_HOST_HEADER": None}))
    assert str(request.url) == "https://epicstaff.example.com/api/sessions/7/"
    assert request.headers["Host"] == "epicstaff.example.com"


async def test_a_host_header_override_is_sent(settings):
    request = await _status_request(settings.model_copy(update={"CHAT_DJANGO_URL": "http://django_app:8000", "CHAT_DJANGO_HOST_HEADER": "localhost"}))
    assert request.url.host == "django_app"
    assert request.headers["Host"] == "localhost"
