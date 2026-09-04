import re
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from urllib.parse import urlparse, parse_qs

import pytest

from utils.twilio_signature import _compute_signature


CHANNEL_TOKEN = "chan-tok-1"
AUTH_TOKEN = "test-auth-token-1234567890"


def _fake_request(
    auth_token: str | None = AUTH_TOKEN,
    url_path: str = f"/voice/{CHANNEL_TOKEN}",
    form_data: dict | None = None,
    base_url: str = "https://testserver",
) -> SimpleNamespace:
    """Minimal stand-in for `starlette.Request`.

    When `auth_token` is truthy, a valid `X-Twilio-Signature` header is
    computed for the request `_twilio_voice_webhook` will reconstruct
    (`{base_url}{url_path}` with no query, form params from `form_data`), so
    signature validation passes. `base_url` must match whatever
    `twilio_voice_webhook_channel` actually resolves for the given channel
    fixture (live_url's host, else ngrok_domain) — signature validation binds
    to that resolved tunnel URL, not to the caller-supplied request host, so
    callers exercising a real ngrok/live_url tunnel must pass it explicitly.
    Pass `auth_token=None` to exercise the "no auth_token configured"
    (fail-closed 503) path.
    """
    form_data = form_data or {}
    headers: dict[str, str] = {"host": "testserver"}
    if auth_token:
        full_url = f"{base_url}{url_path}"
        headers["X-Twilio-Signature"] = _compute_signature(
            full_url, form_data, auth_token
        )

    async def form():
        return form_data

    return SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        headers=headers,
        url=SimpleNamespace(path=url_path, query=""),
        form=form,
    )


def _channel_with_nested_webhook_trigger(
    live_url: str | None, ngrok_domain: str | None
):
    """Mimics `RealtimeChannelInternalSerializer`/`_TwilioChannelInternalSerializer` output:
    `ngrok_config` and `live_url` live under `twilio.webhook_trigger`, not directly on
    `twilio` (see regression — they were previously read one level too shallow,
    always resolving to an empty string and forcing a 503).
    """
    return {
        "realtime_agent_definition": 42,
        "twilio": {
            "account_sid": "AC123",
            "auth_token": AUTH_TOKEN,
            "phone_number": "+10000000000",
            "webhook_trigger": {
                "id": 1,
                "path": "abc123",
                "provider_type": "ngrok",
                "ngrok_config": {"name": "n1", "domain": ngrok_domain, "region": "eu"},
                "localhost_config": None,
                "live_url": live_url,
            },
        },
    }


@pytest.mark.asyncio
async def test_voice_webhook_prefers_ngrok_domain_over_live_url(monkeypatch):
    """`live_url` belongs to the generic webhook-trigger microservice and already
    carries a `/webhooks/{path}` prefix (e.g. `/webhooks/abc123`). Reusing it to
    build the Media Stream WS URL produces a URL that nginx's `/webhooks/`
    location block intercepts and routes to the unrelated `webhook` stub service
    (no WebSocket handler), breaking the Twilio Media Stream handshake. The bare
    `ngrok_domain` must be used instead whenever it is available — this is the
    real-world case where both fields are populated simultaneously.
    """
    from api.main import twilio_voice_webhook_channel

    channel = _channel_with_nested_webhook_trigger(
        live_url="https://live.example.ngrok.io/webhooks/abc123",
        ngrok_domain="fallback.example.ngrok.io",
    )

    async def fake_resolve(channel_token):
        return channel.get("realtime_agent_definition"), channel

    monkeypatch.setattr("api.main._resolve_channel_agent", fake_resolve)

    response = await twilio_voice_webhook_channel(
        CHANNEL_TOKEN,
        request=_fake_request(base_url="https://live.example.ngrok.io"),
    )

    assert response.status_code == 200
    body = response.body.decode()
    assert f"wss://fallback.example.ngrok.io/voice/{CHANNEL_TOKEN}/stream" in body
    assert "/webhooks/" not in body


@pytest.mark.asyncio
async def test_voice_webhook_falls_back_to_ngrok_domain_when_no_live_url(monkeypatch):
    from api.main import twilio_voice_webhook_channel

    channel = _channel_with_nested_webhook_trigger(
        live_url=None,
        ngrok_domain="fallback.example.ngrok.io",
    )

    async def fake_resolve(channel_token):
        return channel.get("realtime_agent_definition"), channel

    monkeypatch.setattr("api.main._resolve_channel_agent", fake_resolve)

    response = await twilio_voice_webhook_channel(
        CHANNEL_TOKEN,
        request=_fake_request(base_url="https://fallback.example.ngrok.io"),
    )

    assert response.status_code == 200
    assert (
        f"wss://fallback.example.ngrok.io/voice/{CHANNEL_TOKEN}/stream"
        in response.body.decode()
    )


@pytest.mark.asyncio
async def test_voice_webhook_falls_back_to_settings_voice_stream_url(monkeypatch):
    """When neither `ngrok_domain` nor `live_url` is available, `voice_stream_url`
    must still fall back to the static `settings.VOICE_STREAM_URL` env var
    (distinct from the `live_url`-over-settings precedence covered below —
    here there is no `live_url` to prefer in the first place)."""
    from api.main import twilio_voice_webhook_channel
    from core.config import settings

    channel = _channel_with_nested_webhook_trigger(live_url=None, ngrok_domain=None)

    async def fake_resolve(channel_token):
        return channel.get("realtime_agent_definition"), channel

    monkeypatch.setattr("api.main._resolve_channel_agent", fake_resolve)
    monkeypatch.setattr(
        settings, "VOICE_STREAM_URL", "wss://static.example.com/voice/stream"
    )

    response = await twilio_voice_webhook_channel(
        CHANNEL_TOKEN, request=_fake_request()
    )

    assert response.status_code == 200
    assert (
        f"wss://static.example.com/voice/{CHANNEL_TOKEN}/stream"
        in response.body.decode()
    )


@pytest.mark.asyncio
async def test_voice_webhook_prefers_live_url_over_settings_voice_stream_url(monkeypatch):
    """`ngrok_domain` is legitimately `None` for free-tier/random-subdomain ngrok
    tunnels. In that case `voice_stream_url` must fall back to `live_url`'s
    resolved host, not silently degrade to the static `settings.VOICE_STREAM_URL`
    env var (which may point at a stale/wrong host). This was the encoded bug:
    the static setting used to be preferred even when a live, active tunnel
    URL was available.
    """
    from api.main import twilio_voice_webhook_channel
    from core.config import settings

    channel = _channel_with_nested_webhook_trigger(
        live_url="https://tunnel-only.example.com/webhooks/abc123", ngrok_domain=None
    )

    async def fake_resolve(channel_token):
        return channel.get("realtime_agent_definition"), channel

    monkeypatch.setattr("api.main._resolve_channel_agent", fake_resolve)
    monkeypatch.setattr(
        settings, "VOICE_STREAM_URL", "wss://static.example.com/voice/stream"
    )

    response = await twilio_voice_webhook_channel(
        CHANNEL_TOKEN,
        request=_fake_request(base_url="https://tunnel-only.example.com"),
    )

    assert response.status_code == 200
    body = response.body.decode()
    assert f"wss://tunnel-only.example.com/voice/{CHANNEL_TOKEN}/stream" in body
    assert "static.example.com" not in body
    assert "/webhooks/" not in body


@pytest.mark.asyncio
async def test_voice_webhook_resolves_voice_stream_url_from_live_url_when_no_ngrok_domain(
    monkeypatch,
):
    """Mirrors `test_voice_webhook_resolves_base_url_from_live_url_when_no_ngrok_domain`
    but asserts on `voice_stream_url` instead of the signature-validation
    `base_url`: a random-subdomain ngrok tunnel (no static `ngrok_domain`
    configured) must still produce a working Media Stream WS URL derived from
    the actual, currently-active tunnel host -- with no static-settings
    fallback needed at all.
    """
    from api.main import twilio_voice_webhook_channel
    from core.config import settings

    channel = _channel_with_nested_webhook_trigger(
        live_url="https://random-abc123.ngrok-free.dev/webhooks/abc123",
        ngrok_domain=None,
    )

    async def fake_resolve(channel_token):
        return channel.get("realtime_agent_definition"), channel

    monkeypatch.setattr("api.main._resolve_channel_agent", fake_resolve)
    monkeypatch.setattr(settings, "VOICE_STREAM_URL", "")

    response = await twilio_voice_webhook_channel(
        CHANNEL_TOKEN,
        request=_fake_request(base_url="https://random-abc123.ngrok-free.dev"),
    )

    assert response.status_code == 200
    body = response.body.decode()
    assert f"wss://random-abc123.ngrok-free.dev/voice/{CHANNEL_TOKEN}/stream" in body
    assert "/webhooks/" not in body


@pytest.mark.asyncio
async def test_voice_webhook_resolves_base_url_from_live_url_when_no_ngrok_domain(
    monkeypatch,
):
    """`ngrok_config.domain` is the static custom-domain setting and is
    legitimately `None` for free-tier/random-subdomain ngrok tunnels.
    `live_url` is provider-agnostic and already reflects the real,
    currently-active tunnel host in that case. `base_url` (used for Twilio
    signature validation) must fall back to `live_url`'s scheme+host instead
    of fail-closed 503'ing just because the static `ngrok_domain` field is
    unset — this is the actual regression: random-subdomain ngrok tunnels
    were fail-closing with 503 even though a valid, live tunnel URL was
    available.
    """
    from api.main import twilio_voice_webhook_channel
    from core.config import settings

    channel = _channel_with_nested_webhook_trigger(
        live_url="https://random-abc123.ngrok-free.dev/webhooks/abc123",
        ngrok_domain=None,
    )

    async def fake_resolve(channel_token):
        return channel.get("realtime_agent_definition"), channel

    monkeypatch.setattr("api.main._resolve_channel_agent", fake_resolve)
    # ngrok_domain is unset, so voice_stream_url falls back to settings —
    # unrelated to (and independent from) the base_url/live_url fix under
    # test here, but required for this call to reach a 200 at all.
    monkeypatch.setattr(settings, "VOICE_STREAM_URL", "wss://static.example.com/voice/stream")

    response = await twilio_voice_webhook_channel(
        CHANNEL_TOKEN,
        request=_fake_request(base_url="https://random-abc123.ngrok-free.dev"),
    )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_voice_webhook_503s_when_no_stream_url_available(monkeypatch):
    from api.main import twilio_voice_webhook_channel
    from core.config import settings
    from fastapi import HTTPException

    channel = _channel_with_nested_webhook_trigger(live_url=None, ngrok_domain=None)

    async def fake_resolve(channel_token):
        return channel.get("realtime_agent_definition"), channel

    monkeypatch.setattr("api.main._resolve_channel_agent", fake_resolve)
    monkeypatch.setattr(settings, "VOICE_STREAM_URL", "")

    with pytest.raises(HTTPException) as exc_info:
        await twilio_voice_webhook_channel(CHANNEL_TOKEN, request=_fake_request())

    assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# stream_token auth: the TwiML <Stream> URL must embed a token that the
# paired WebSocket route can validate before accepting the connection.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_webhook_embeds_stream_token_bound_to_channel(monkeypatch):
    from api.main import stream_token_repository, twilio_voice_webhook_channel

    channel = _channel_with_nested_webhook_trigger(
        live_url=None, ngrok_domain="fallback.example.ngrok.io"
    )

    async def fake_resolve(channel_token):
        return channel.get("realtime_agent_definition"), channel

    monkeypatch.setattr("api.main._resolve_channel_agent", fake_resolve)

    response = await twilio_voice_webhook_channel(
        CHANNEL_TOKEN,
        request=_fake_request(base_url="https://fallback.example.ngrok.io"),
    )
    body = response.body.decode()

    stream_url = urlparse(body.split('url="')[1].split('"')[0])
    assert stream_url.path == f"/voice/{CHANNEL_TOKEN}/stream"
    token = parse_qs(stream_url.query)["stream_token"][0]
    assert token

    # The minted token must be bound to this exact channel_token and be
    # single-use — the WebSocket handler's `consume()` call, not a raw
    # string comparison here, is what actually gates the media bridge.
    assert stream_token_repository.consume(token, bound_key=CHANNEL_TOKEN) is True
    assert stream_token_repository.consume(token, bound_key=CHANNEL_TOKEN) is False


@pytest.mark.asyncio
async def test_voice_webhook_embeds_stream_token_as_twiml_parameter(monkeypatch):
    """Twilio does not reliably forward the `?stream_token=...` query string
    on `<Stream url="...">` to the actual Media Stream WebSocket (confirmed
    in production — see EST voice-call regression). The nested
    `<Parameter name="stream_token" value="...">` element is the mechanism
    Twilio actually relays, via `start.customParameters` on the WS leg — so
    the TwiML must always include it."""
    import re

    from api.main import stream_token_repository, twilio_voice_webhook_channel

    channel = _channel_with_nested_webhook_trigger(
        live_url=None, ngrok_domain="fallback.example.ngrok.io"
    )

    async def fake_resolve(channel_token):
        return channel.get("realtime_agent_definition"), channel

    monkeypatch.setattr("api.main._resolve_channel_agent", fake_resolve)

    response = await twilio_voice_webhook_channel(
        CHANNEL_TOKEN,
        request=_fake_request(base_url="https://fallback.example.ngrok.io"),
    )
    body = response.body.decode()

    match = re.search(r'<Parameter name="stream_token" value="([^"]+)"', body)
    assert match, f'expected a <Parameter name="stream_token"> element, got: {body}'
    param_token = match.group(1)
    assert param_token

    # Must be the exact same single-use token embedded in the URL query
    # string fallback, not a second, independently-minted one.
    stream_url = urlparse(body.split('url="')[1].split('"')[0])
    query_token = parse_qs(stream_url.query)["stream_token"][0]
    assert param_token == query_token

    assert stream_token_repository.consume(param_token, bound_key=CHANNEL_TOKEN) is True


@pytest.mark.asyncio
async def test_voice_webhook_xml_escapes_url_and_token(monkeypatch):
    """A raw `&` (or other XML-special character) in the stream URL or token
    must never reach the TwiML body unescaped — an unescaped `&` inside an
    XML attribute is invalid XML and can truncate/corrupt the value Twilio's
    XML parser extracts from the element."""
    from api.main import twilio_voice_webhook_channel

    channel = _channel_with_nested_webhook_trigger(
        live_url=None, ngrok_domain="fallback.example.ngrok.io"
    )

    async def fake_resolve(channel_token):
        return channel.get("realtime_agent_definition"), channel

    monkeypatch.setattr("api.main._resolve_channel_agent", fake_resolve)

    response = await twilio_voice_webhook_channel(
        CHANNEL_TOKEN,
        request=_fake_request(base_url="https://fallback.example.ngrok.io"),
    )
    body = response.body.decode()

    # The URL now carries two query params (stream_token appended to none in
    # this case, but exercised generally): verify no literal, unescaped `&`
    # appears anywhere as a bare ampersand not part of `&amp;`.
    for bare_amp in re.finditer(r"&(?!amp;)", body):
        pytest.fail(
            f"found an unescaped '&' in TwiML body at pos {bare_amp.start()}: {body}"
        )

    # And the produced XML must actually be well-formed.
    ET.fromstring(body)


# ---------------------------------------------------------------------------
# Fail-closed: signature validation must never be silently skipped.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_webhook_503s_when_auth_token_not_configured(monkeypatch):
    """A missing/unset `auth_token` must fail closed (503), not fall through
    to skipping signature validation entirely (that was the original,
    unauthenticated-webhook vulnerability)."""
    from api.main import twilio_voice_webhook_channel
    from fastapi import HTTPException

    channel = _channel_with_nested_webhook_trigger(
        live_url=None, ngrok_domain="fallback.example.ngrok.io"
    )
    channel["twilio"]["auth_token"] = None

    async def fake_resolve(channel_token):
        return channel["realtime_agent_definition"], channel

    monkeypatch.setattr("api.main._resolve_channel_agent", fake_resolve)

    with pytest.raises(HTTPException) as exc_info:
        await twilio_voice_webhook_channel(
            CHANNEL_TOKEN, request=_fake_request(auth_token=None)
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Twilio auth not configured"


# ---------------------------------------------------------------------------
# Legacy `realtime_agent` alone is no longer a usable destination — Django's
# `InitRealtimeSerializer` dropped `agent_id` entirely, so a channel still
# pointing only at the removed legacy staff agent must be rejected up front.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_webhook_404s_when_channel_only_has_legacy_agent(monkeypatch):
    """A channel config with `realtime_agent` set and `realtime_agent_definition`
    null has no usable destination and must be rejected with a clear 404
    before any TwiML is generated or Django's init-realtime is ever called."""
    from api.main import twilio_voice_webhook_channel
    from fastapi import HTTPException

    channel = {
        "realtime_agent": 42,
        "realtime_agent_definition": None,
        "twilio": {"auth_token": AUTH_TOKEN},
    }

    async def fake_resolve(channel_token):
        return channel.get("realtime_agent_definition"), channel

    monkeypatch.setattr("api.main._resolve_channel_agent", fake_resolve)

    with pytest.raises(HTTPException) as exc_info:
        await twilio_voice_webhook_channel(CHANNEL_TOKEN, request=_fake_request())

    assert exc_info.value.status_code == 404
    assert "legacy" in exc_info.value.detail.lower()
    assert "42" in exc_info.value.detail
