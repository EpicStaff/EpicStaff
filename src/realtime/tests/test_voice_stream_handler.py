"""
Security regression tests for the previously-unauthenticated Twilio Media
Stream WebSocket routes (`/voice/{channel_token}/stream` and the legacy
`/voice/stream`).

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
    """StreamTokenRepository (and any other SingletonMeta instance) must not
    leak minted/consumed tokens across tests."""
    SingletonMeta._instances.clear()
    yield
    SingletonMeta._instances.clear()


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


# ---------------------------------------------------------------------------
# _voice_stream_handler — always accepts, then gates on the `start` event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_stream_token_rejected_after_accept():
    """No token in `start.customParameters` and none in the query string ->
    rejected. The socket is accepted (Twilio's handshake requirement) but
    closed immediately, before any Django/provider call."""
    from api.main import _voice_stream_handler

    ws = _make_ws(receive_payloads=[_start_event(stream_token=None)])
    await _voice_stream_handler(
        ws, agent_id=1, auth_token=None, stream_token=None, stream_bound_key="chan-1"
    )

    ws.accept.assert_awaited_once()
    ws.close.assert_awaited_once_with(code=1008)


@pytest.mark.asyncio
async def test_bogus_stream_token_rejected():
    from api.main import _voice_stream_handler

    ws = _make_ws(receive_payloads=[_start_event(stream_token="never-minted")])
    await _voice_stream_handler(
        ws,
        agent_id=1,
        auth_token=None,
        stream_token=None,
        stream_bound_key="chan-1",
    )

    ws.accept.assert_awaited_once()
    ws.close.assert_awaited_once_with(code=1008)


@pytest.mark.asyncio
async def test_token_minted_for_different_channel_rejected():
    from api.main import _voice_stream_handler, stream_token_repository

    token = stream_token_repository.mint(bound_key="chan-1")
    ws = _make_ws(receive_payloads=[_start_event(stream_token=token)])
    await _voice_stream_handler(
        ws, agent_id=1, auth_token=None, stream_token=None, stream_bound_key="chan-2"
    )

    ws.accept.assert_awaited_once()
    ws.close.assert_awaited_once_with(code=1008)


@pytest.mark.asyncio
async def test_expired_stream_token_rejected(monkeypatch):
    import infrastructure.persistence.stream_token_repository as repo_module
    from api.main import _voice_stream_handler, stream_token_repository

    fake_time = {"now": 1000.0}
    monkeypatch.setattr(repo_module.time, "monotonic", lambda: fake_time["now"])

    token = stream_token_repository.mint(bound_key="chan-1")
    fake_time["now"] += stream_token_repository.ttl_seconds + 1

    ws = _make_ws(receive_payloads=[_start_event(stream_token=token)])
    await _voice_stream_handler(
        ws, agent_id=1, auth_token=None, stream_token=None, stream_bound_key="chan-1"
    )

    ws.accept.assert_awaited_once()
    ws.close.assert_awaited_once_with(code=1008)


@pytest.mark.asyncio
async def test_stream_token_is_single_use():
    """A stream_token must not authenticate a second WebSocket connection —
    otherwise a leaked TwiML URL is a reusable credential."""
    from api.main import _voice_stream_handler, stream_token_repository

    token = stream_token_repository.mint(bound_key="chan-1")

    ws1 = _make_ws(receive_payloads=[_start_event(stream_token=token)])
    patcher = _mock_unreachable_django()
    try:
        await _voice_stream_handler(
            ws1,
            agent_id=1,
            auth_token=None,
            stream_token=None,
            stream_bound_key="chan-1",
        )
    finally:
        patcher.stop()
    ws1.accept.assert_awaited_once()
    _assert_not_auth_rejected(ws1)

    ws2 = _make_ws(receive_payloads=[_start_event(stream_token=token)])
    await _voice_stream_handler(
        ws2, agent_id=1, auth_token=None, stream_token=None, stream_bound_key="chan-1"
    )
    ws2.accept.assert_awaited_once()
    ws2.close.assert_awaited_once_with(code=1008)


@pytest.mark.asyncio
async def test_valid_stream_token_in_start_custom_parameters_accepts_connection():
    """The real Twilio delivery path: token arrives via
    `start.customParameters`, not the query string."""
    from api.main import _voice_stream_handler, stream_token_repository

    token = stream_token_repository.mint(bound_key="chan-1")
    ws = _make_ws(receive_payloads=[_start_event(stream_token=token)])

    patcher = _mock_unreachable_django()
    try:
        await _voice_stream_handler(
            ws, agent_id=1, auth_token=None, stream_token=None, stream_bound_key="chan-1"
        )
    finally:
        patcher.stop()

    ws.accept.assert_awaited_once()
    _assert_not_auth_rejected(ws)


@pytest.mark.asyncio
async def test_valid_stream_token_via_query_param_fallback_still_accepted():
    """If a caller (e.g. test tooling, or a Twilio config that does forward
    query params) presents the token via the query string instead of
    `start.customParameters`, it's still honoured as a fallback."""
    from api.main import _voice_stream_handler, stream_token_repository

    token = stream_token_repository.mint(bound_key="chan-1")
    ws = _make_ws(receive_payloads=[_start_event(stream_token=None)])

    patcher = _mock_unreachable_django()
    try:
        await _voice_stream_handler(
            ws, agent_id=1, auth_token=None, stream_token=token, stream_bound_key="chan-1"
        )
    finally:
        patcher.stop()

    ws.accept.assert_awaited_once()
    _assert_not_auth_rejected(ws)


@pytest.mark.asyncio
async def test_twilio_never_sending_query_param_does_not_block_valid_call():
    """Reproduces the exact production regression: TwiML embedded the token
    in the URL query string, but Twilio never relayed it to this WS (query
    param arrives as None). The call must still succeed because the token
    also travels via `start.customParameters`."""
    from api.main import _voice_stream_handler, stream_token_repository

    token = stream_token_repository.mint(bound_key="chan-1")
    ws = _make_ws(receive_payloads=[_start_event(stream_token=token)])

    patcher = _mock_unreachable_django()
    try:
        await _voice_stream_handler(
            ws,
            agent_id=1,
            auth_token=None,
            stream_token=None,  # Twilio dropped the query param, as observed live.
            stream_bound_key="chan-1",
        )
    finally:
        patcher.stop()

    ws.accept.assert_awaited_once()
    _assert_not_auth_rejected(ws)


@pytest.mark.asyncio
async def test_no_start_event_received_rejected():
    """If the socket never produces a readable `start` event at all (e.g.
    Twilio hangs up immediately), there's no token from either source and the
    connection must still be rejected rather than proceeding."""
    from api.main import _voice_stream_handler

    ws = _make_ws(receive_payloads=None)  # receive_text raises immediately
    await _voice_stream_handler(
        ws, agent_id=1, auth_token=None, stream_token=None, stream_bound_key="chan-1"
    )

    ws.accept.assert_awaited_once()
    ws.close.assert_awaited_once_with(code=1008)


# ---------------------------------------------------------------------------
# /voice/{channel_token}/stream route wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_stream_channel_route_rejects_missing_token(monkeypatch):
    from api.main import voice_stream_channel

    async def fake_resolve(channel_token):
        return 42, {}

    monkeypatch.setattr("api.main._resolve_channel_agent", fake_resolve)

    ws = _make_ws(receive_payloads=[_start_event(stream_token=None)])
    await voice_stream_channel("chan-1", ws, stream_token=None)

    ws.accept.assert_awaited_once()
    ws.close.assert_awaited_once_with(code=1008)


@pytest.mark.asyncio
async def test_voice_stream_channel_route_accepts_matching_token_from_start_event(
    monkeypatch,
):
    from api.main import voice_stream_channel, stream_token_repository

    async def fake_resolve(channel_token):
        return 42, {}

    monkeypatch.setattr("api.main._resolve_channel_agent", fake_resolve)

    token = stream_token_repository.mint(bound_key="chan-1")
    ws = _make_ws(receive_payloads=[_start_event(stream_token=token)])

    patcher = _mock_unreachable_django()
    try:
        await voice_stream_channel("chan-1", ws, stream_token=None)
    finally:
        patcher.stop()

    ws.accept.assert_awaited_once()
    _assert_not_auth_rejected(ws)


@pytest.mark.asyncio
async def test_voice_stream_channel_route_rejects_token_minted_for_other_channel(
    monkeypatch,
):
    from api.main import voice_stream_channel, stream_token_repository

    async def fake_resolve(channel_token):
        return 42, {}

    monkeypatch.setattr("api.main._resolve_channel_agent", fake_resolve)

    token = stream_token_repository.mint(bound_key="some-other-channel")
    ws = _make_ws(receive_payloads=[_start_event(stream_token=token)])
    await voice_stream_channel("chan-1", ws, stream_token=None)

    ws.accept.assert_awaited_once()
    ws.close.assert_awaited_once_with(code=1008)


# ---------------------------------------------------------------------------
# Legacy /voice/stream route wiring — same posture, distinct bound_key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_voice_stream_route_rejects_missing_token(monkeypatch):
    from api.main import voice_stream

    async def fake_get_voice_settings():
        return {"voice_agent": 7, "voice_agent_definition": None}

    monkeypatch.setattr("api.main.get_voice_settings", fake_get_voice_settings)

    ws = _make_ws(receive_payloads=[_start_event(stream_token=None)])
    await voice_stream(ws, stream_token=None)

    ws.accept.assert_awaited_once()
    ws.close.assert_awaited_once_with(code=1008)


@pytest.mark.asyncio
async def test_legacy_voice_stream_route_rejects_channel_bound_token(monkeypatch):
    """A stream_token minted for the channel-token route must not authenticate
    the legacy, channel-less global-singleton route."""
    from api.main import voice_stream, stream_token_repository

    async def fake_get_voice_settings():
        return {"voice_agent": 7, "voice_agent_definition": None}

    monkeypatch.setattr("api.main.get_voice_settings", fake_get_voice_settings)

    token = stream_token_repository.mint(bound_key="chan-1")
    ws = _make_ws(receive_payloads=[_start_event(stream_token=token)])
    await voice_stream(ws, stream_token=None)

    ws.accept.assert_awaited_once()
    ws.close.assert_awaited_once_with(code=1008)


@pytest.mark.asyncio
async def test_legacy_voice_stream_route_accepts_legacy_bound_token_from_start_event(
    monkeypatch,
):
    from api.main import _LEGACY_STREAM_BOUND_KEY, voice_stream, stream_token_repository

    async def fake_get_voice_settings():
        return {"voice_agent": 7, "voice_agent_definition": None}

    monkeypatch.setattr("api.main.get_voice_settings", fake_get_voice_settings)

    token = stream_token_repository.mint(bound_key=_LEGACY_STREAM_BOUND_KEY)
    ws = _make_ws(receive_payloads=[_start_event(stream_token=token)])

    patcher = _mock_unreachable_django()
    try:
        await voice_stream(ws, stream_token=None)
    finally:
        patcher.stop()

    ws.accept.assert_awaited_once()
    _assert_not_auth_rejected(ws)
