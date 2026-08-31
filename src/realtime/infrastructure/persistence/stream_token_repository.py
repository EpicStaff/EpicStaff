import secrets
import time
from collections import OrderedDict

from utils.singleton_meta import SingletonMeta

DEFAULT_STREAM_TOKEN_TTL_SECONDS = 120
DEFAULT_MAX_STREAM_TOKENS = 200


class StreamTokenRepository(metaclass=SingletonMeta):
    """Short-lived, single-use secrets gating the unauthenticated Twilio
    Media Stream WebSocket route (`/voice/{channel_token}/stream`).

    Twilio's Media Streams WS leg carries none of Twilio's verifiable
    request headers (no `X-Twilio-Signature`), so the stream endpoint itself
    cannot authenticate the caller. Instead, a token is minted when the
    TwiML `<Stream>` element is built in the paired `POST /voice/{channel_token}`
    webhook (which *is* signature-validated) and embedded both as a
    `?stream_token=...` query param on `<Stream url="...">` (best-effort
    fallback) and as a nested `<Parameter name="stream_token" value="...">`.

    Confirmed in production (2026-08): Twilio does not forward the query
    string on the `<Stream>` url to the WebSocket leg — only the
    `<Parameter>` value, delivered inside the first `start` event's
    `customParameters`, reliably arrives. Because that token is only known
    *after* the WebSocket handshake, the gate can no longer sit before
    `.accept()`; `api/main.py::_voice_stream_handler` now accepts the socket
    and validates the token from the `start` event immediately afterward,
    closing with code 1008 before any Django/provider/audio work happens if
    it's missing or invalid.

    Mirrors the TTL + single-use pattern already used by
    `ConnectionRepository` (EST-1869) for the `realtime_agents:schema`
    connection_key handshake.
    """

    def __init__(
        self,
        ttl_seconds: int = DEFAULT_STREAM_TOKEN_TTL_SECONDS,
        max_tokens: int = DEFAULT_MAX_STREAM_TOKENS,
    ):
        # token -> (bound_key, expires_at)
        self._store: "OrderedDict[str, tuple[str | None, float]]" = OrderedDict()
        self.ttl_seconds = ttl_seconds
        self.max_tokens = max_tokens

    def mint(self, bound_key: str | None = None) -> str:
        """Generate and store a new single-use token bound to `bound_key`
        (e.g. the `channel_token`, or a fixed sentinel for the legacy,
        channel-less route). Evicts the oldest entry if over capacity."""
        if len(self._store) >= self.max_tokens:
            self._store.popitem(last=False)
        token = secrets.token_urlsafe(32)
        expires_at = time.monotonic() + self.ttl_seconds
        self._store[token] = (bound_key, expires_at)
        return token

    def consume(self, token: str | None, bound_key: str | None = None) -> bool:
        """Validate and immediately invalidate `token` (single-use, whether
        or not validation succeeds). Returns True only if the token exists,
        has not expired, and was minted for this exact `bound_key`."""
        if not token:
            return False
        entry = self._store.pop(token, None)
        if entry is None:
            return False
        stored_bound_key, expires_at = entry
        if time.monotonic() >= expires_at:
            return False
        return stored_bound_key == bound_key
