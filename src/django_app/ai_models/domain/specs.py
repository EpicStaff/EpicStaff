"""Value objects the model catalog is made of.

Plain frozen dataclasses: no Django, no LiteLLM, so the catalog can be built, stored and
read anywhere.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum

REASONING_EFFORT_PARAMETER = "reasoning_effort"
NO_REASONING_EFFORT = "none"
THINKING_PARAMETER = "thinking"


class ModelKind(StrEnum):
    """What a model is used for. LiteLLM calls `LLM` mode "chat"; only the adapter knows."""

    LLM = "llm"
    EMBEDDING = "embedding"
    TRANSCRIPTION = "transcription"


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    """One model setting as the UI shows it and the validator checks it.

    `limit_from` names a model limit (e.g. `"max_output_tokens"`) that replaces `maximum`
    for models that report it. `overrides` maps a provider to field replacements.
    `default` None means "not set": the setting is not sent.
    """

    name: str
    value_type: str
    control: str
    label: str
    help_text: str
    group: str
    default: object | None
    minimum: float | None
    maximum: float | None
    step: float | None
    options: tuple[str, ...]
    limit_from: str | None
    draft: bool
    overrides: Mapping[str, Mapping[str, object]]

    def for_provider(self, provider: str) -> "ParameterSpec":
        """Return this spec with the provider's overrides applied."""
        return replace(self, **self.overrides.get(provider, {}))


@dataclass(frozen=True, slots=True)
class ConnectionFieldSpec:
    """One provider connection field and the LiteLLM argument it is sent as.

    A `secret` field holds an `epicstaff_secret(<name>)` marker, never a value. An
    `endpoint` field decides where the config's requests, and the secrets they carry,
    go: a host, a region or deployment that picks one, or a project or compartment that
    picks whose account is called. Changing it on a config that carries a secret needs
    secrets:USE.
    """

    name: str
    value_type: str
    control: str
    label: str
    required: bool
    secret: bool
    endpoint: bool
    litellm_argument: str


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """A provider and what EpicStaff can run with it.

    `kinds` are the kinds the runtime supports for this provider. `common_parameters`
    are the settings offered for a model the catalog does not know (a custom model).
    `aliases` are other names a database `Provider` row stores this provider under
    (e.g. `google_ai` for `gemini`). `main_secret_argument` is the LiteLLM argument the
    config's API-key secret is sent as.
    """

    name: str
    label: str
    recommended: bool
    kinds: tuple[ModelKind, ...]
    custom_models: bool
    connection_fields: tuple[ConnectionFieldSpec, ...]
    common_parameters: Mapping[ModelKind, tuple[str, ...]]
    aliases: tuple[str, ...] = ()
    main_secret_argument: str = "api_key"


@dataclass(frozen=True, slots=True)
class DefaultThinkingSpec:
    """How a model that thinks when no `thinking` setting is sent behaves.

    `default_effort` is the effort it then thinks at. `thinking_type_to_turn_off` is the
    `thinking.type` that turns thinking off, because LiteLLM sends nothing for a stored
    `reasoning_effort` "none" and the model would think anyway; None means thinking
    cannot be turned off, so "none" is not offered. `provider_accepts_thinking` is False
    where LiteLLM does not list `thinking` for the model's provider: "none" is then sent
    as stored, since LiteLLM would drop `thinking` or refuse the call.
    """

    default_effort: str
    thinking_type_to_turn_off: str | None
    provider_accepts_thinking: bool = True


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """One model of one provider and kind.

    `limits` holds model limits such as `max_output_tokens`; `options` holds per-model
    choices that narrow a choice setting's options (e.g. `reasoning_effort` levels).
    `default_thinking` is set for a model that thinks by default.
    """

    name: str
    provider: str
    kind: ModelKind
    recommended: bool
    deprecation_date: date | None
    limits: Mapping[str, float]
    parameter_names: tuple[str, ...]
    options: Mapping[str, tuple[str, ...]]
    default_thinking: DefaultThinkingSpec | None = None
