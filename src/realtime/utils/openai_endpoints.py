"""Derive OpenAI-compatible endpoint URLs from an optional per-org `base_url` override.

EST-3702: lets a realtime session point at a local/self-hosted or proxy
OpenAI-compatible endpoint instead of the hardcoded `api.openai.com` host.
When `base_url` is unset, both derivations fall back to today's exact
behavior (a byte-for-byte hardcoded literal for the WS URL, and `None` for
the chat/summarization HTTP client so the SDK's own default applies).
"""

_DEFAULT_REALTIME_WS_URL = "wss://api.openai.com/v1/realtime"

_SCHEME_TO_WS = {
    "http": "ws",
    "https": "wss",
}


def derive_realtime_ws_url(base_url: str | None) -> str:
    """Return the OpenAI realtime WebSocket URL for `base_url`.

    None/empty `base_url` returns the exact current hardcoded literal.
    Otherwise `base_url` must already carry an explicit `http://`/`https://`
    scheme (no scheme is auto-prepended); the scheme is swapped to its `ws`/
    `wss` counterpart, any trailing slash is stripped, and `/v1/realtime` is
    appended.
    """
    if not base_url:
        return _DEFAULT_REALTIME_WS_URL

    scheme, _, rest = base_url.partition("://")
    if not rest or scheme not in _SCHEME_TO_WS:
        raise ValueError(
            f"base_url must start with 'http://' or 'https://', got: {base_url!r}"
        )

    ws_scheme = _SCHEME_TO_WS[scheme]
    rest = rest.rstrip("/")
    return f"{ws_scheme}://{rest}/v1/realtime"


def derive_chat_http_url(base_url: str | None) -> str | None:
    """Return the OpenAI-compatible chat/completions base URL for `base_url`.

    None/empty `base_url` returns `None`, so callers pass `base_url=None`
    into `AsyncOpenAI` and get its exact current SDK-default behavior.
    Otherwise strips any trailing slash and appends `/v1`, keeping the
    scheme as-is.
    """
    if not base_url:
        return None

    return f"{base_url.rstrip('/')}/v1"
