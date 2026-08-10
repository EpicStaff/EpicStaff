from types import SimpleNamespace

import pytest


CHANNEL_TOKEN = "chan-tok-1"


def _fake_request() -> SimpleNamespace:
    """Minimal stand-in for `starlette.Request` — only `.client.host` is touched on the
    no-signature-validation branch (auth_token falsy)."""
    return SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={})


def _channel_with_nested_webhook_trigger(live_url: str | None, ngrok_domain: str | None):
    """Mimics `RealtimeChannelInternalSerializer`/`_TwilioChannelInternalSerializer` output:
    `ngrok_config` and `live_url` live under `twilio.webhook_trigger`, not directly on
    `twilio` (see EST-1869 regression — they were previously read one level too shallow,
    always resolving to an empty string and forcing a 503).
    """
    return {
        "realtime_agent": 42,
        "twilio": {
            "account_sid": "AC123",
            "auth_token": None,
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
        return channel["realtime_agent"], channel

    monkeypatch.setattr("api.main._resolve_channel_agent", fake_resolve)

    response = await twilio_voice_webhook_channel(CHANNEL_TOKEN, request=_fake_request())

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
        return channel["realtime_agent"], channel

    monkeypatch.setattr("api.main._resolve_channel_agent", fake_resolve)

    response = await twilio_voice_webhook_channel(CHANNEL_TOKEN, request=_fake_request())

    assert response.status_code == 200
    assert (
        f"wss://fallback.example.ngrok.io/voice/{CHANNEL_TOKEN}/stream"
        in response.body.decode()
    )


@pytest.mark.asyncio
async def test_voice_webhook_falls_back_to_settings_voice_stream_url(monkeypatch):
    from api.main import twilio_voice_webhook_channel
    from core.config import settings

    channel = _channel_with_nested_webhook_trigger(live_url=None, ngrok_domain=None)

    async def fake_resolve(channel_token):
        return channel["realtime_agent"], channel

    monkeypatch.setattr("api.main._resolve_channel_agent", fake_resolve)
    monkeypatch.setattr(settings, "VOICE_STREAM_URL", "wss://static.example.com/voice/stream")

    response = await twilio_voice_webhook_channel(CHANNEL_TOKEN, request=_fake_request())

    assert response.status_code == 200
    assert (
        f"wss://static.example.com/voice/{CHANNEL_TOKEN}/stream"
        in response.body.decode()
    )


@pytest.mark.asyncio
async def test_voice_webhook_503s_when_no_stream_url_available(monkeypatch):
    from api.main import twilio_voice_webhook_channel
    from core.config import settings
    from fastapi import HTTPException

    channel = _channel_with_nested_webhook_trigger(live_url=None, ngrok_domain=None)

    async def fake_resolve(channel_token):
        return channel["realtime_agent"], channel

    monkeypatch.setattr("api.main._resolve_channel_agent", fake_resolve)
    monkeypatch.setattr(settings, "VOICE_STREAM_URL", "")

    with pytest.raises(HTTPException) as exc_info:
        await twilio_voice_webhook_channel(CHANNEL_TOKEN, request=_fake_request())

    assert exc_info.value.status_code == 503
