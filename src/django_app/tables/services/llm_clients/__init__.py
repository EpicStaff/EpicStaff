from __future__ import annotations

from .base import (
    BaseLLMClient,
    DoneEvent,
    StreamEvent,
    StructuredEvent,
    TokenEvent,
    ToolCallEvent,
    ToolResultEvent,
    ToolSpec,
    UnsupportedLLMProviderError,
)
from .litellm_client import LiteLLMClient

__all__ = [
    "BaseLLMClient",
    "DoneEvent",
    "LiteLLMClient",
    "StreamEvent",
    "StructuredEvent",
    "TokenEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "ToolSpec",
    "UnsupportedLLMProviderError",
    "get_llm_client",
]


def get_llm_client(
    llm_config,
    output_schema: dict | None = None,
    *,
    api_key: str | None,
) -> BaseLLMClient:
    """Return a LiteLLMClient for the given LLMConfig.

    ``output_schema`` is forwarded to the client constructor so callers can
    request structured JSON output (e.g. ``response_format: json_schema``)
    without mutating the persisted ``LLMConfig`` row.

    ``api_key`` must be resolved by the caller (via
    ``tables.services.secrets.secret_resolver``) before calling this function;
    it has no default so omitting it fails loudly instead of silently sending
    an unauthenticated request. ``None`` is a legitimate explicit value for
    providers that need no credential. Async callers must wrap the resolution
    in ``sync_to_async`` — LiteLLMClient itself must not touch the ORM.

    The model string is derived inside LiteLLMClient from
    ``llm_config.model.llm_provider.name`` + ``llm_config.model.name``, so any
    provider supported by LiteLLM works without any code change here.

    Raises ``UnsupportedLLMProviderError`` when the model or provider is missing.
    """
    return LiteLLMClient(llm_config, api_key=api_key, output_schema=output_schema)
