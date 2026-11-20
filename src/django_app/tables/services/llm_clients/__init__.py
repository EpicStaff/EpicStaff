from __future__ import annotations

import re

from django.conf import settings
from foundation.cryptographer import FernetRotatedCryptographer
from pydantic import ValidationError
from src.shared.models.ai_providers import LLMConfigData
from tables.services.converter_service import ConverterService
from tables.services.secrets.encryption import MAX_TEXT_BYTES
from tables.services.secrets.pinned_principal_rules import assert_may_resolve_markers
from tables.services.secrets.secret_resolver import (
    extract_secret_marker_names,
    secret_resolver,
)

from .base import (
    TOOL_USE_FAILED_CODE,
    USER_VISIBLE_PROVIDER_ERROR_CODES,
    BaseLLMClient,
    DoneEvent,
    InvalidLLMConfigError,
    LLMProviderError,
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
    "TOOL_USE_FAILED_CODE",
    "USER_VISIBLE_PROVIDER_ERROR_CODES",
    "BaseLLMClient",
    "DoneEvent",
    "InvalidLLMConfigError",
    "LLMProviderError",
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

# The marker syntax SecretResolver seals into, opened here as a receiving service opens it.
_SEALED_MARKER_RE = re.compile(r"epicstaff_secret\(\s*([^)]+?)\s*\)")


def get_llm_client(
    llm_config,
    output_schema: dict | None = None,
    *,
    principal,
) -> BaseLLMClient:
    """Return a LiteLLMClient for the given LLMConfig, its secrets resolved.

    ``output_schema`` is forwarded to the client constructor so callers can
    request structured JSON output (e.g. ``response_format: json_schema``)
    without mutating the persisted ``LLMConfig`` row.

    The config is converted to ``LLMConfigData`` here, so LiteLLMClient never
    sees the ORM row, and its secrets are resolved for the config's organization
    as a run's are: the API key, and the ``epicstaff_secret(<name>)`` markers in
    its extra headers and connection (a connection marker outside a secret field
    never gets this far, see ``connection_arguments``). Callers must
    ``select_related("model__llm_provider")``. Resolving queries the database:
    async callers wrap this function in ``sync_to_async``.

    Args:
        principal: The pinned-org principal the call is made for
            (``pinned_principal_of_user``), None for a person. Required, so no
            caller skips the marker rule by omission: a principal's markers must
            name secrets it may reference, as when a run it starts resolves them.

    Raises ``UnsupportedLLMProviderError`` when the config has no model or the
    model name is empty, ``InvalidLLMConfigError`` when a stored value (e.g.
    ``extra_headers``) has a shape LLMConfigData rejects,
    ``SecretMarkerNotReferenceableError`` when a marker names a secret
    ``principal`` may not reference, and ``SecretResolutionError`` when a secret
    cannot be resolved.
    """
    model = llm_config.model
    if model is None:
        raise UnsupportedLLMProviderError("(no model configured)")
    try:
        config_data = ConverterService().convert_llm_config_data(llm_config)
    except ValidationError as exc:
        field_names = sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"]})
        raise InvalidLLMConfigError(llm_config.pk, field_names) from exc
    if principal is not None:
        assert_may_resolve_markers(
            principal=principal,
            names=extract_secret_marker_names(config_data.connection)
            | extract_secret_marker_names(config_data.extra_headers),
        )
    resolved = _open_sealed_secrets(
        secret_resolver.resolve_payload(payload=config_data, org_id=llm_config.org_id)
    )
    provider = model.llm_provider
    return LiteLLMClient(
        resolved,
        provider_name=provider.name if provider else None,
        api_key=resolved.api_key,
        output_schema=output_schema,
    )


def _open_sealed_secrets(config: LLMConfigData) -> LLMConfigData:
    """Return `config` with the secrets `resolve_payload` sealed for transport opened again.

    `resolve_payload` seals every secret it fills for the service that receives it; this
    client calls the provider from django_app itself, so it opens them with the same key.
    Holds the plaintext secrets: never log the result.
    """
    cryptographer = FernetRotatedCryptographer(
        settings.SECRETS_TRANSPORT_KEY,
        settings.SECRETS_TRANSPORT_PREVIOUS_KEYS,
        hkdf_info=settings.SECRETS_TRANSPORT_HKDF_INFO.encode(),
        max_data_size=MAX_TEXT_BYTES,
    )

    def open_markers(values: dict[str, str] | None) -> dict[str, str] | None:
        if not values:
            return values
        return {
            key: (
                _SEALED_MARKER_RE.sub(lambda match: cryptographer.decrypt(match.group(1)), value)
                if isinstance(value, str)
                else value
            )
            for key, value in values.items()
        }

    return config.model_copy(
        update={
            "api_key": cryptographer.decrypt(config.api_key) if config.api_key else config.api_key,
            "extra_headers": open_markers(config.extra_headers),
            "connection": open_markers(config.connection),
        }
    )
