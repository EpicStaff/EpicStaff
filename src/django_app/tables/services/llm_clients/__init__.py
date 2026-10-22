from __future__ import annotations

from pydantic import ValidationError
from tables.services.converter_service import ConverterService

from .base import (
    BaseLLMClient,
    DoneEvent,
    InvalidLLMConfigError,
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
    "InvalidLLMConfigError",
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
    in ``sync_to_async``.

    The config is converted to ``LLMConfigData`` here, so LiteLLMClient never
    sees the ORM row. Callers must ``select_related("model__llm_provider")``:
    this function then issues no query and is safe to call from async code.

    Raises ``UnsupportedLLMProviderError`` when the config has no model or the
    model name is empty, and ``InvalidLLMConfigError`` when a stored value (e.g.
    ``extra_headers``) has a shape LLMConfigData rejects.
    """
    model = llm_config.model
    if model is None:
        raise UnsupportedLLMProviderError("(no model configured)")
    try:
        config_data = ConverterService().convert_llm_config_data(llm_config)
    except ValidationError as exc:
        field_names = sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"]})
        raise InvalidLLMConfigError(llm_config.pk, field_names) from exc
    provider = model.llm_provider
    return LiteLLMClient(
        config_data,
        provider_name=provider.name if provider else None,
        api_key=api_key,
        output_schema=output_schema,
    )
