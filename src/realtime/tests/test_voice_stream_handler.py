"""
Security regression tests for the previously-unauthenticated Twilio Media
Stream WebSocket route `/voice/{channel_token}/stream`.

Both routes require a short-lived, single-use `stream_token` — minted by the
paired (signature-validated) TwiML webhook — to be validated via
`StreamTokenRepository` before any Django `init-realtime` call, provider
connection, or audio is processed.

Confirmed in production (2026-08 voice-call regression): Twilio does NOT
forward the `?stream_token=...` query string embedded in the TwiML
`<Stream url="...">` to this WebSocket connection. The token is delivered
instead via the nested `<Parameter name="stream_token" value="...">` element,
which Twilio relays inside the first `start` event's `customParameters`. That
means the token is unknown until *after* the WS handshake, so `.accept()`
itself can no longer gate on it: the socket is always accepted, but the
handler closes immediately — before touching Django/the provider/any audio —
if the token (from `start.customParameters`, falling back to the query
param) fails validation.
"""

import json
from unittest.mock import AsyncMock, call, patch

import pytest
from infrastructure.persistence.stream_token_repository import StreamTokenRepository
from utils.singleton_meta import SingletonMeta


def _assert_not_auth_rejected(ws: AsyncMock) -> None:
    """Close code 1008 is reserved for the stream_token auth gate. Some of
    these tests intentionally make the downstream Django `init-realtime`
    call fail (network unreachable), which legitimately closes the socket
    for an unrelated reason — that's fine; we only care that the auth gate
    itself didn't reject the (valid) token."""
    assert call(code=1008) not in ws.close.call_args_list


@pytest.fixture(autouse=True)
def reset_singletons():
    """`StreamTokenRepository` must not leak minted/consumed tokens across
    tests. Only this one class's registered instance is dropped -- clearing
    the whole `SingletonMeta._instances` dict would also orphan unrelated
    singletons (e.g. `api.main`'s module-level `connection_repository`,
    which other test modules rely on being the SAME instance `api.main`
    itself uses)."""
    SingletonMeta._instances.pop(StreamTokenRepository, None)
    yield
    SingletonMeta._instances.pop(StreamTokenRepository, None)


def _start_event(stream_token: str | None = None) -> str:
    """Build a realistic Twilio `start` event frame. When `stream_token` is
    given, it's carried in `start.customParameters` exactly as Twilio relays
    a `<Parameter name="stream_token" value="...">` nested under `<Stream>`."""
    custom_parameters = {"stream_token": stream_token} if stream_token else {}
    return json.dumps(
        {
            "event": "start",
            "sequenceNumber": "1",
            "start": {
                "accountSid": "AC123",
                "streamSid": "MZ123",
                "callSid": "CA123",
                "tracks": ["inbound"],
                "customParameters": custom_parameters,
                "mediaFormat": {
                    "encoding": "audio/x-mulaw",
                    "sampleRate": 8000,
                    "channels": 1,
                },
            },
            "streamSid": "MZ123",
        }
    )


def _make_ws(receive_payloads: list[str] | None = None) -> AsyncMock:
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    if receive_payloads is not None:
        ws.receive_text = AsyncMock(side_effect=receive_payloads)
    else:
        ws.receive_text = AsyncMock(side_effect=Exception("no data"))
    return ws


def _mock_unreachable_django(monkeypatch_target: str = "api.main.httpx.AsyncClient"):
    """Context manager stub: makes the post-accept `init-realtime` HTTP call
    fail immediately, so tests only exercise the token-validation gate
    without depending on a real Django/Redis backend."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=Exception("network unreachable"))
    patcher = patch(monkeypatch_target)
    mock_client_cls = patcher.start()
    mock_client_cls.return_value.__aenter__.return_value = mock_client
    return patcher


@pytest.fixture
def channel_with_agent(monkeypatch):
    """The channel resolves to agent definition 42 (Django's channel lookup is external)."""

    async def resolve(channel_token):
        return 42, {}

    monkeypatch.setattr("api.main._resolve_channel_agent", resolve)


@pytest.fixture
def unreachable_django():
    """The post-accept init-realtime call fails at once, so a test stops right after the gate."""
    patcher = _mock_unreachable_django()
    yield
    patcher.stop()


def _expired_token(monkeypatch, stream_token_repository) -> str:
    import infrastructure.persistence.stream_token_repository as repo_module

    clock = {"now": 1000.0}
    monkeypatch.setattr(repo_module.time, "monotonic", lambda: clock["now"])
    token = stream_token_repository.mint(bound_key="chan-1")
    clock["now"] += stream_token_repository.ttl_seconds + 1
    return token


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("make_token", "frames"),
    [
        pytest.param(lambda repo, monkeypatch: None, "start", id="no-token"),
        pytest.param(lambda repo, monkeypatch: "never-minted", "start", id="bogus-token"),
        pytest.param(lambda repo, monkeypatch: repo.mint(bound_key="some-other-channel"), "start", id="other-channels-token"),
        pytest.param(lambda repo, monkeypatch: _expired_token(monkeypatch, repo), "start", id="expired-token"),
        # Twilio hung up before sending a start event: no token from either source.
        pytest.param(lambda repo, monkeypatch: None, None, id="no-start-event"),
    ],
)
async def test_stream_without_a_valid_token_is_closed_before_anything_runs(
    channel_with_agent, monkeypatch, make_token, frames
):
    """The token is only known from the first start event, so the socket is accepted
    (Twilio's handshake requires it) and closed with 1008 before Django is called."""
    from api.main import stream_token_repository, voice_stream_channel

    token = make_token(stream_token_repository, monkeypatch)
    ws = _make_ws(receive_payloads=[_start_event(stream_token=token)] if frames else None)

    with patch("api.main.httpx.AsyncClient") as django_client:
        await voice_stream_channel("chan-1", ws, stream_token=None)

    ws.accept.assert_awaited_once()
    ws.close.assert_awaited_once_with(code=1008)
    django_client.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "via",
    [
        # Twilio relays <Parameter name="stream_token"> in start.customParameters and
        # drops the URL query string (the production regression this guards).
        "start-custom-parameters",
        # Tooling or a Twilio config that does forward query params still works.
        "query-param",
    ],
)
async def test_valid_stream_token_passes_the_gate(channel_with_agent, unreachable_django, via):
    from api.main import stream_token_repository, voice_stream_channel

    token = stream_token_repository.mint(bound_key="chan-1")
    ws = _make_ws(receive_payloads=[_start_event(stream_token=token if via == "start-custom-parameters" else None)])

    await voice_stream_channel("chan-1", ws, stream_token=token if via == "query-param" else None)

    ws.accept.assert_awaited_once()
    _assert_not_auth_rejected(ws)


@pytest.mark.asyncio
async def test_stream_token_is_single_use(channel_with_agent, unreachable_django):
    """Otherwise a leaked TwiML URL would be a reusable credential."""
    from api.main import stream_token_repository, voice_stream_channel

    token = stream_token_repository.mint(bound_key="chan-1")
    first = _make_ws(receive_payloads=[_start_event(stream_token=token)])
    await voice_stream_channel("chan-1", first, stream_token=None)
    _assert_not_auth_rejected(first)

    second = _make_ws(receive_payloads=[_start_event(stream_token=token)])
    await voice_stream_channel("chan-1", second, stream_token=None)

    second.close.assert_awaited_once_with(code=1008)


# ---------------------------------------------------------------------------
# Legacy `realtime_agent` alone has no usable destination — Django's
# `InitRealtimeSerializer` dropped `agent_id` entirely, so a channel still
# pointing only at the removed legacy staff agent must fail fast at the
# front door instead of reaching Django's init-realtime with a payload it
# no longer accepts.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_stream_channel_route_rejects_legacy_only_channel_without_calling_django(
    monkeypatch,
):
    """A channel bound only to the removed legacy staff agent (no
    `realtime_agent_definition`) must be rejected before the WebSocket is
    even accepted, and must never reach Django's init-realtime call."""
    from api.main import voice_stream_channel

    async def fake_resolve(channel_token):
        return None, {"realtime_agent": 42, "realtime_agent_definition": None}

    monkeypatch.setattr("api.main._resolve_channel_agent", fake_resolve)

    with patch("api.main.httpx.AsyncClient") as mock_client_cls:
        ws = _make_ws(receive_payloads=[_start_event(stream_token=None)])
        await voice_stream_channel("chan-1", ws, stream_token=None)

    mock_client_cls.assert_not_called()
    ws.accept.assert_not_awaited()
    ws.close.assert_awaited_once_with(code=1008)


@pytest.mark.asyncio
async def test_voice_stream_channel_route_posts_only_agent_definition_id(monkeypatch):
    """A channel resolved to an `agent_definition_id` must post exactly
    `{"agent_definition_id": ..., "config": ...}` to init-realtime — never
    the removed `agent_id` field."""
    from api.main import voice_stream_channel, stream_token_repository

    async def fake_resolve(channel_token):
        return 99, {"realtime_agent_definition": 99}

    monkeypatch.setattr("api.main._resolve_channel_agent", fake_resolve)

    token = stream_token_repository.mint(bound_key="chan-1")
    ws = _make_ws(receive_payloads=[_start_event(stream_token=token)])

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json = lambda: {"connection_key": "nonexistent-key"}
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    with patch("api.main.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        await voice_stream_channel("chan-1", ws, stream_token=None)

    mock_client.post.assert_awaited_once()
    payload = mock_client.post.call_args.kwargs["json"]
    assert payload == {
        "agent_definition_id": 99,
        "config": {
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
        },
    }
    assert "agent_id" not in payload
