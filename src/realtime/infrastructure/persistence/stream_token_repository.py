import secrets
import time
from collections import OrderedDict

from utils.singleton_meta import SingletonMeta

DEFAULT_STREAM_TOKEN_TTL_SECONDS = 120
# A token stays pending until its first use or until the TTL expires. A call that
# reaches the Media Stream `start` event frees its slot within a second or two, but a
# call abandoned before then holds it for the full TTL. The cap therefore bounds the
# call setups on one channel within the last TTL that have not reached the stream.
# 20 is far above what a normal line produces in that window, yet keeps one
# channel's share of memory small.
DEFAULT_MAX_STREAM_TOKENS_PER_KEY = 20


class StreamTokenRepository(metaclass=SingletonMeta):
    """Short-lived, single-use secrets gating the unauthenticated Twilio
    Media Stream WebSocket route (`/voice/{channel_token}/stream`).

    Twilio's Media Streams WS leg carries none of Twilio's verifiable
    request headers (no `X-Twilio-Signature`), so the stream endpoint itself
    cannot authenticate the caller. Instead, a token is minted when the
    TwiML `<Stream>` element is built in the paired `POST /voice/{channel_token}`
    webhook — only after its `X-Twilio-Signature` has been validated — and
    embedded both as a `?stream_token=...` query param on `<Stream url="...">`
    (best-effort fallback) and as a nested
    `<Parameter name="stream_token" value="...">`.

    Confirmed in production (2026-08): Twilio does not forward the query
    string on the `<Stream>` url to the WebSocket leg — only the
    `<Parameter>` value, delivered inside the first `start` event's
    `customParameters`, reliably arrives. Because that token is only known
    *after* the WebSocket handshake, the gate can no longer sit before
    `.accept()`; `api/main.py::_voice_stream_handler` now accepts the socket
    and validates the token from the `start` event immediately afterward,
    closing with code 1008 before any Django/provider/audio work happens if
    it's missing or invalid.

    Capacity is per `bound_key` (per channel), never shared. Authenticating the
    webhook is necessary but not sufficient: every tenant holds its own
    channel's Twilio auth token and can sign as many requests to its own route
    as it likes, so a shared cap would let one tenant evict — and drop — other
    organisations' pending calls. Memory stays bounded because only
    authenticated requests mint, each channel is capped, and expired tokens are
    purged on every mint.

    Mirrors the TTL + single-use pattern already used by
    `ConnectionRepository` for the `realtime_agents:schema`
    connection_key handshake.
    """

    def __init__(
        self,
        ttl_seconds: int = DEFAULT_STREAM_TOKEN_TTL_SECONDS,
        max_tokens_per_key: int = DEFAULT_MAX_STREAM_TOKENS_PER_KEY,
    ):
        # token -> (bound_key, expires_at), in mint order. The TTL is constant,
        # so mint order is also expiry order.
        self._store: OrderedDict[str, tuple[str, float]] = OrderedDict()
        # bound_key -> that key's live tokens, in mint order (values unused).
        self._tokens_by_key: dict[str, OrderedDict[str, None]] = {}
        self.ttl_seconds = ttl_seconds
        self.max_tokens_per_key = max_tokens_per_key

    def mint(self, bound_key: str) -> str:
        """Generate and store a new single-use token bound to `bound_key`.

        Drops expired tokens first. If `bound_key` already holds
        `max_tokens_per_key` live tokens, its own oldest one is evicted;
        another key's live token is never evicted.

        Args:
            bound_key: Route the token is valid for — the `channel_token`.
        """
        now = time.monotonic()
        self._purge_expired(now)
        key_tokens = self._tokens_by_key.setdefault(bound_key, OrderedDict())
        if len(key_tokens) >= self.max_tokens_per_key:
            evicted_token, _ = key_tokens.popitem(last=False)
            del self._store[evicted_token]
        token = secrets.token_urlsafe(32)
        self._store[token] = (bound_key, now + self.ttl_seconds)
        key_tokens[token] = None
        return token

    def consume(self, token: str | None, bound_key: str) -> bool:
        """Validate and immediately invalidate `token` (single-use, whether
        or not validation succeeds). Returns True only if the token exists,
        has not expired, and was minted for this exact `bound_key`."""
        if not token:
            return False
        entry = self._store.pop(token, None)
        if entry is None:
            return False
        stored_bound_key, expires_at = entry
        self._forget_key_token(stored_bound_key, token)
        if time.monotonic() >= expires_at:
            return False
        return stored_bound_key == bound_key

    def _purge_expired(self, now: float) -> None:
        while self._store:
            token, (stored_bound_key, expires_at) = next(iter(self._store.items()))
            if expires_at > now:
                return
            del self._store[token]
            self._forget_key_token(stored_bound_key, token)

    def _forget_key_token(self, bound_key: str, token: str) -> None:
        key_tokens = self._tokens_by_key[bound_key]
        del key_tokens[token]
        if not key_tokens:
            del self._tokens_by_key[bound_key]
