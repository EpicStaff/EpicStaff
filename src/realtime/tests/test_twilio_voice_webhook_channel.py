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


OTHER_CHANNEL_TOKEN = "another-orgs-channel"
FALLBACK_DOMAIN = "fallback.example.ngrok.io"


@pytest.fixture
def isolated_stream_token_repository(request, monkeypatch):
    """An empty token store holding at most 1 pending token per channel (override with
    `@pytest.mark.parametrize("isolated_stream_token_repository", [n], indirect=True)`), wired
    into `api.main`. The previously registered singleton is restored afterwards."""
    from infrastructure.persistence.stream_token_repository import StreamTokenRepository
    from utils.singleton_meta import SingletonMeta

    monkeypatch.delitem(SingletonMeta._instances, StreamTokenRepository, raising=False)
    repository = StreamTokenRepository(max_tokens_per_key=getattr(request, "param", 1))
    # Recorded after the delitem, so teardown unregisters this instance before the
    # delitem's undo puts back whatever was registered before.
    monkeypatch.setitem(SingletonMeta._instances, StreamTokenRepository, repository)
    monkeypatch.setattr("api.main.stream_token_repository", repository)
    return repository


async def _signed_call_stream_token() -> str:
    from api.main import twilio_voice_webhook_channel

    response = await twilio_voice_webhook_channel(
        CHANNEL_TOKEN, request=_fake_request(base_url=f"https://{FALLBACK_DOMAIN}")
    )
    (parameter,) = ET.fromstring(response.body).find("./Connect/Stream").findall("Parameter")
    return parameter.get("value")


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
async def test_twilio_form_post_is_parsed_and_answered_with_twiml(resolve_channel):
    """Twilio posts its call parameters form-encoded; the real request parser must
    read them, or no signature can be validated and every call fails."""
    from httpx import ASGITransport, AsyncClient

    from api.main import app

    base_url = "https://fallback.example.ngrok.io"
    path = f"/voice/{CHANNEL_TOKEN}"
    call_parameters = {"CallSid": "CA123", "From": "+15550001111", "To": "+10000000000"}
    resolve_channel(_channel_with_nested_webhook_trigger(live_url=None, ngrok_domain="fallback.example.ngrok.io"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            path,
            data=call_parameters,
            headers={"X-Twilio-Signature": _compute_signature(f"{base_url}{path}", call_parameters, AUTH_TOKEN)},
        )

    assert response.status_code == 200
    assert ET.fromstring(response.content).find("./Connect/Stream") is not None


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


@pytest.mark.asyncio
@pytest.mark.parametrize("isolated_stream_token_repository", [2], indirect=True)
async def test_signed_calls_filling_a_channels_quota_never_drop_another_channels_call(
    resolve_channel, isolated_stream_token_repository
):
    """Every tenant holds its own channel's auth token and can sign any number of
    calls to its own route; that must only ever cost its own pending calls."""
    pending_token_of_another_channel = isolated_stream_token_repository.mint(bound_key=OTHER_CHANNEL_TOKEN)
    resolve_channel(_channel_with_nested_webhook_trigger(live_url=None, ngrok_domain=FALLBACK_DOMAIN))

    oldest, middle, newest = [await _signed_call_stream_token() for _ in range(3)]

    assert isolated_stream_token_repository.consume(pending_token_of_another_channel, bound_key=OTHER_CHANNEL_TOKEN) is True
    # One token per call: with a quota of 2, only the first call's token is gone.
    assert isolated_stream_token_repository.consume(oldest, bound_key=CHANNEL_TOKEN) is False
    assert isolated_stream_token_repository.consume(middle, bound_key=CHANNEL_TOKEN) is True
    assert isolated_stream_token_repository.consume(newest, bound_key=CHANNEL_TOKEN) is True


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
async def test_call_is_refused_without_twiml(
    resolve_channel, isolated_stream_token_repository, channel, request_kwargs, status, detail
):
    """A refused call mints nothing: the channel's quota is 1 and already used by a
    pending call, so any mint would evict that call's token."""
    from fastapi import HTTPException

    from api.main import twilio_voice_webhook_channel

    pending_token = isolated_stream_token_repository.mint(bound_key=CHANNEL_TOKEN)
    resolve_channel(channel())

    with pytest.raises(HTTPException) as refused:
        await twilio_voice_webhook_channel(CHANNEL_TOKEN, request=_fake_request(**request_kwargs))

    assert refused.value.status_code == status
    if isinstance(detail, re.Pattern):
        assert detail.search(refused.value.detail)
    else:
        assert refused.value.detail == detail
    assert isolated_stream_token_repository.consume(pending_token, bound_key=CHANNEL_TOKEN) is True
