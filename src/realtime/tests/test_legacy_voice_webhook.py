"""Coverage for the DEPRECATED, but still frontend-configurable, legacy
`POST /voice` TwiML webhook (`VoiceSettings` global singleton). Confirms it
mints a stream_token bound to the legacy sentinel, distinct from the
channel-token route's per-channel tokens.
"""

import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from utils.twilio_signature import _compute_signature

AUTH_TOKEN = "test-auth-token-1234567890"


def _fake_request(
    auth_token: str | None = AUTH_TOKEN,
    url_path: str = "/voice",
    form_data: dict | None = None,
) -> SimpleNamespace:
    """Minimal stand-in for `starlette.Request`.

    When `auth_token` is truthy, a valid `X-Twilio-Signature` header is
    computed for `https://testserver{url_path}` (no query, `form_data`
    params), matching what `_twilio_voice_webhook` reconstructs. Pass
    `auth_token=None` to exercise the fail-closed (503) path.
    """
    form_data = form_data or {}
    headers: dict[str, str] = {"host": "testserver"}
    if auth_token:
        full_url = f"https://testserver{url_path}"
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


@pytest.mark.asyncio
async def test_legacy_voice_webhook_embeds_stream_token_bound_to_legacy_sentinel(
    monkeypatch,
):
    from api.main import (
        _LEGACY_STREAM_BOUND_KEY,
        stream_token_repository,
        twilio_voice_webhook,
    )

    async def fake_get_voice_settings():
        return {
            "twilio_auth_token": AUTH_TOKEN,
            "voice_stream_url": "wss://legacy.example.com/voice/stream",
        }

    monkeypatch.setattr("api.main.get_voice_settings", fake_get_voice_settings)

    response = await twilio_voice_webhook(request=_fake_request())
    body = response.body.decode()

    stream_url = urlparse(body.split('url="')[1].split('"')[0])
    assert stream_url.path == "/voice/stream"
    token = parse_qs(stream_url.query)["stream_token"][0]
    assert token

    # Bound to the legacy sentinel, not a channel_token, and single-use.
    assert stream_token_repository.consume(token, bound_key=_LEGACY_STREAM_BOUND_KEY) is True
    assert stream_token_repository.consume(token, bound_key=_LEGACY_STREAM_BOUND_KEY) is False


@pytest.mark.asyncio
async def test_legacy_voice_webhook_embeds_stream_token_as_twiml_parameter(monkeypatch):
    """Same fix as the channel-token route: the nested `<Parameter
    name="stream_token">` element is the mechanism Twilio actually relays to
    the WS leg (via `start.customParameters`), since the query string on the
    `<Stream url="...">` is not reliably forwarded."""
    from api.main import twilio_voice_webhook

    async def fake_get_voice_settings():
        return {
            "twilio_auth_token": AUTH_TOKEN,
            "voice_stream_url": "wss://legacy.example.com/voice/stream",
        }

    monkeypatch.setattr("api.main.get_voice_settings", fake_get_voice_settings)

    response = await twilio_voice_webhook(request=_fake_request())
    body = response.body.decode()

    match = re.search(r'<Parameter name="stream_token" value="([^"]+)"', body)
    assert match, f"expected a <Parameter name=\"stream_token\"> element, got: {body}"
    assert match.group(1)


@pytest.mark.asyncio
async def test_legacy_voice_webhook_503s_when_no_stream_url_available(monkeypatch):
    """auth_token is valid/signed here so the request passes signature
    validation and reaches the stream-url check specifically (distinct from
    the auth-not-configured 503 covered separately below)."""
    from api.main import twilio_voice_webhook
    from fastapi import HTTPException

    async def fake_get_voice_settings():
        return {"twilio_auth_token": AUTH_TOKEN, "voice_stream_url": ""}

    monkeypatch.setattr("api.main.get_voice_settings", fake_get_voice_settings)
    monkeypatch.setattr("api.main.settings.VOICE_STREAM_URL", "")

    with pytest.raises(HTTPException) as exc_info:
        await twilio_voice_webhook(request=_fake_request())

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "No voice stream URL configured"


@pytest.mark.asyncio
async def test_legacy_voice_webhook_503s_when_auth_token_not_configured(monkeypatch):
    """A missing/unset `auth_token` must fail closed (503), not skip
    signature validation entirely (the original vulnerability)."""
    from api.main import twilio_voice_webhook
    from fastapi import HTTPException

    async def fake_get_voice_settings():
        return {
            "twilio_auth_token": None,
            "voice_stream_url": "wss://legacy.example.com/voice/stream",
        }

    monkeypatch.setattr("api.main.get_voice_settings", fake_get_voice_settings)

    with pytest.raises(HTTPException) as exc_info:
        await twilio_voice_webhook(request=_fake_request(auth_token=None))

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Twilio auth not configured"
