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


@pytest.fixture
def resolve_channel(monkeypatch):
    """Django's channel lookup is external; each test sets the channel it returns."""

    def _set(channel):
        async def resolve(channel_token):
            return channel.get("realtime_agent_definition"), channel

        monkeypatch.setattr("api.main._resolve_channel_agent", resolve)

    return _set


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("live_url", "ngrok_domain", "signed_base_url", "stream_host"),
    [
        # live_url belongs to the webhook microservice and carries a /webhooks/ prefix that
        # nginx routes elsewhere, so the bare ngrok domain wins whenever it is set.
        ("https://live.example.ngrok.io/webhooks/abc123", "fallback.example.ngrok.io", "https://live.example.ngrok.io", "fallback.example.ngrok.io"),
        (None, "fallback.example.ngrok.io", "https://fallback.example.ngrok.io", "fallback.example.ngrok.io"),
        # Free-tier ngrok has no static domain; live_url's host is the active tunnel.
        ("https://random-abc123.ngrok-free.dev/webhooks/abc123", None, "https://random-abc123.ngrok-free.dev", "random-abc123.ngrok-free.dev"),
    ],
    ids=["ngrok-domain-over-live-url", "ngrok-domain-only", "live-url-only"],
)
async def test_signed_call_is_sent_to_the_channels_media_stream(
    resolve_channel, live_url, ngrok_domain, signed_base_url, stream_host
):
    """A 200 proves the signature was checked against the right tunnel URL."""
    from api.main import twilio_voice_webhook_channel

    resolve_channel(_channel_with_nested_webhook_trigger(live_url=live_url, ngrok_domain=ngrok_domain))

    response = await twilio_voice_webhook_channel(CHANNEL_TOKEN, request=_fake_request(base_url=signed_base_url))

    assert response.status_code == 200
    stream_url = urlparse(ET.fromstring(response.body).find("./Connect/Stream").get("url"))
    assert (stream_url.scheme, stream_url.netloc, stream_url.path) == ("wss", stream_host, f"/voice/{CHANNEL_TOKEN}/stream")


@pytest.mark.asyncio
async def test_twiml_carries_one_single_use_stream_token_bound_to_the_channel(resolve_channel):
    """Twilio drops the URL query on the Media Stream leg and relays only the nested
    <Parameter>, so the token travels in both, and they must be the same token."""
    from api.main import stream_token_repository, twilio_voice_webhook_channel

    resolve_channel(_channel_with_nested_webhook_trigger(live_url=None, ngrok_domain="fallback.example.ngrok.io"))

    response = await twilio_voice_webhook_channel(
        CHANNEL_TOKEN, request=_fake_request(base_url="https://fallback.example.ngrok.io")
    )

    # Parsing fails on any unescaped XML-special character in the URL or token.
    stream = ET.fromstring(response.body).find("./Connect/Stream")
    query_token = parse_qs(urlparse(stream.get("url")).query)["stream_token"][0]
    (parameter,) = stream.findall("Parameter")
    assert (parameter.get("name"), parameter.get("value")) == ("stream_token", query_token)
    assert re.search(r"&(?!amp;)", response.body.decode()) is None
    assert stream_token_repository.consume(query_token, bound_key=CHANNEL_TOKEN) is True
    assert stream_token_repository.consume(query_token, bound_key=CHANNEL_TOKEN) is False


def _legacy_only_channel():
    return {"realtime_agent": 42, "realtime_agent_definition": None, "twilio": {"auth_token": AUTH_TOKEN}}


def _channel_without_auth_token():
    channel = _channel_with_nested_webhook_trigger(live_url=None, ngrok_domain="fallback.example.ngrok.io")
    channel["twilio"]["auth_token"] = None
    return channel


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("channel", "request_kwargs", "status", "detail"),
    [
        # Not signed by Twilio with this channel's auth token.
        (
            lambda: _channel_with_nested_webhook_trigger(live_url=None, ngrok_domain="fallback.example.ngrok.io"),
            {"auth_token": "someone-elses-token", "base_url": "https://fallback.example.ngrok.io"},
            403, "Invalid Twilio signature",
        ),
        # A missing auth token must fail closed, never skip signature validation.
        (_channel_without_auth_token, {"auth_token": None}, 503, "Twilio auth not configured"),
        (
            lambda: _channel_with_nested_webhook_trigger(live_url=None, ngrok_domain=None),
            {}, 503, "No tunnel domain configured for this channel's webhook_trigger.",
        ),
        # Django no longer accepts the removed legacy staff agent as a destination.
        (_legacy_only_channel, {}, 404, re.compile(r"(?i)legacy.*42|42.*legacy")),
    ],
    ids=["bad-signature", "no-auth-token", "no-tunnel", "legacy-agent-only"],
)
async def test_call_is_refused_without_twiml(resolve_channel, channel, request_kwargs, status, detail):
    from fastapi import HTTPException

    from api.main import twilio_voice_webhook_channel

    resolve_channel(channel())

    with pytest.raises(HTTPException) as refused:
        await twilio_voice_webhook_channel(CHANNEL_TOKEN, request=_fake_request(**request_kwargs))

    assert refused.value.status_code == status
    if isinstance(detail, re.Pattern):
        assert detail.search(refused.value.detail)
    else:
        assert refused.value.detail == detail
