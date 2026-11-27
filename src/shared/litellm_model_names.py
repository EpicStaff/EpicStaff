"""The single rule for turning an LLM config row into a litellm model name.

Used by the agent service, crew and django_app, so every service sends the same model
to the same provider. Imports litellm, so only import it from a service that has litellm.

The checks about a model (`litellm_model_capability`, `litellm_refuses_sampling`,
`litellm_needs_cache_markers`, `litellm_generation_kwargs`) take its model identity:
`litellm_call_model(provider, model_name)` without a deployment id. An Azure deployment
is a user-chosen label litellm has no metadata for, so only the string a call is made
with carries it; the model catalog and a run then ask litellm about the same model.
"""

import functools
from typing import TYPE_CHECKING

import litellm
from litellm.llms.anthropic.common_utils import supports_anthropic_cache_control

if TYPE_CHECKING:
    from .models.ai_providers import LLMConfigData

__all__ = [
    "PROVIDER_ALIASES",
    "SAMPLING_PARAMETERS",
    "litellm_call_model",
    "litellm_generation_kwargs",
    "litellm_lookup_name",
    "litellm_model_capability",
    "litellm_needs_cache_markers",
    "litellm_refuses_sampling",
    "litellm_routed_provider",
]

# Provider rows whose name is not a litellm provider, mapped to the litellm provider their
# stored model names are prefixed with (e.g. "google_ai" rows hold "gemini/gemini-flash-latest").
PROVIDER_ALIASES = {
    "google_ai": "gemini",
    "novita_ai": "novita",
    "aws_sagemaker": "sagemaker",
    "featherless-ai": "featherless_ai",
}

_AZURE_PROVIDERS = frozenset({"azure", "azure_openai"})

# The settings left out for a model `litellm_refuses_sampling` names.
SAMPLING_PARAMETERS = frozenset({"temperature", "top_p", "top_k"})

# Non-default values: litellm passes temperature 1 even to models that refuse sampling.
_SAMPLING_PROBE_VALUES = {"temperature": 0.5, "top_p": 0.9}

# The thinking-based sampling rules cover only Anthropic's own API: Claude reached through
# bedrock, vertex_ai or azure_ai shares a litellm provider prefix with non-Claude models,
# so they cannot be keyed on the provider there.
_ANTHROPIC_PROVIDER = "anthropic"


def litellm_lookup_name(provider_name: str | None, model_name: str) -> str:
    """Return the `<provider>/<model>` key litellm's model map knows this model by.

    Only the row's own provider counts: `openai/gpt-oss-120b` on a Groq row is a Groq
    model id and becomes `groq/openai/gpt-oss-120b`.

    Azure rows are looked up by the model name, never the deployment id: a deployment
    is a user-chosen label litellm has no metadata for.
    """
    model_name = model_name.strip()
    provider = (provider_name or "").lower().strip()
    if not provider:
        return model_name
    provider = PROVIDER_ALIASES.get(provider, provider)
    if model_name.startswith(f"{provider}/"):
        return model_name
    return f"{provider}/{model_name}"


def _openai_row_model(model_name: str) -> str:
    # litellm routes a vendor-prefixed name ("anthropic/claude-sonnet-4-6") and a known bare
    # name ("claude-sonnet-4-6") to its own provider. An unknown bare name (a self-hosted
    # OpenAI-compatible server's model) has no provider to route to, so it is OpenAI's.
    # get_llm_provider is a local table lookup (no network I/O).
    if "/" in model_name:
        return model_name
    try:
        litellm.get_llm_provider(model=model_name)
    except litellm.exceptions.BadRequestError:
        return f"openai/{model_name}"
    return model_name


def litellm_call_model(
    provider_name: str | None, model_name: str, deployment_id: str | None = None
) -> str:
    """Return the model string to pass to a litellm call for this LLM config row.

    The row's own provider wins. Azure rows call the deployment (falling back to the
    model name when none is set). OpenAI rows and rows without a provider keep the model
    name as stored, except that an OpenAI row's bare name litellm does not know becomes
    `openai/<name>`; every other provider follows `litellm_lookup_name`.
    """
    provider = (provider_name or "").lower().strip()
    if not provider:
        return model_name.strip()
    if provider == "openai":
        return _openai_row_model(model_name.strip())
    if provider in _AZURE_PROVIDERS:
        deployment = (deployment_id or model_name).strip()
        return f"azure/{deployment}"
    return litellm_lookup_name(provider_name, model_name)


def litellm_routed_provider(model: str) -> str:
    """Return the provider litellm sends a `litellm_call_model` result to.

    This, not the row's provider, decides provider-specific request rules: an OpenAI row
    keeps `claude-sonnet-4-6` bare and litellm routes it to Anthropic.
    get_llm_provider is a local table lookup (no network I/O).
    """
    try:
        return litellm.get_llm_provider(model=model)[1]
    except litellm.exceptions.BadRequestError:
        # litellm does not know the model: keep its prefix, and a bare name is OpenAI's.
        return model.split("/", 1)[0] if "/" in model else "openai"


def litellm_model_capability(model: str, capability: str) -> bool | None:
    """Return a capability flag (e.g. `supports_forced_tool_use`) from litellm's model map.

    Reads `litellm.model_cost` directly because `get_model_info` drops flags it has no
    typed field for. Looks `model` (the model identity: `litellm_call_model(provider,
    model_name)` without a deployment id) up as given, then without its first `provider/`
    prefix, since the map keys many models only by their bare name. That fallback means a
    gateway-prefixed name (e.g. a Claude model behind an OpenAI-compatible gateway)
    inherits the flags of the bare model name. Returns None when neither key carries the
    flag.
    """
    for key in (model, model.split("/", 1)[-1]):
        flag = litellm.model_cost.get(key, {}).get(capability)
        if flag is not None:
            return flag
    return None


@functools.cache
def litellm_refuses_sampling(model: str) -> bool:
    """Return True when litellm will not send temperature or top_p to this model.

    `model` is the model identity: `litellm_call_model(provider, model_name)` without a
    deployment id, never a deployment label. The map's `supports_sampling_params: false` alone is too broad: litellm still sends
    both to some flagged models (Gemini 3+). So a flagged model is also run through
    litellm's own parameter mapping (no network I/O), once per model per process.
    The probe drops instead of raising and compares the result, so a process-wide
    `litellm.drop_params = True` cannot change the answer. A probe that fails for any
    other reason (e.g. an unknown provider) answers False.
    """
    if litellm_model_capability(model, "supports_sampling_params") is not False:
        return False
    try:
        model_name, provider = _model_and_provider(model)
        without_sampling = _mapped_params(model_name, provider)
        return any(
            _mapped_params(model_name, provider, **{name: value}) == without_sampling
            for name, value in _SAMPLING_PROBE_VALUES.items()
        )
    # The probe only decides whether to drop settings: when litellm cannot answer, the
    # call sends them and the provider decides.
    except Exception:
        return False


@functools.cache
def litellm_needs_cache_markers(model: str) -> bool:
    """Return True when this model takes Anthropic `cache_control` markers.

    `model` is the model identity: `litellm_call_model(provider, model_name)` without a
    deployment id, never a deployment label. Asks litellm's own rule, the one its marker injection uses: a Claude model served by
    Anthropic, Bedrock, Vertex AI or Azure AI that the map flags for prompt caching.
    Claude through a gateway (OpenRouter, GitHub Copilot, Databricks) answers False.
    Any litellm failure, e.g. an unknown provider, answers False.
    """
    try:
        model_name, provider = _model_and_provider(model)
        return supports_anthropic_cache_control(model_name, provider)
    # Markers are an optimisation: a model litellm cannot place is sent without them.
    except Exception:
        return False


def litellm_generation_kwargs(
    config: "LLMConfigData", *, model: str, exclude: set[str] | None = None
) -> dict:
    """Return the generation parameters of `config` to pass to litellm, omitting unset ones.

    Generation params only: `parameters` plus `timeout`. The model string,
    `connection_kwargs()`, extra_headers, store, response_format and tools stay with each
    caller.

    Sampling params the provider would reject are left out. A model litellm refuses
    sampling for (`litellm_refuses_sampling`: where litellm itself drops the settings,
    e.g. Claude Opus 4.7 and later on Anthropic, Bedrock, Vertex AI and Azure AI) gets no
    temperature, top_p or top_k at all, not even temperature 1, which newer Anthropic API
    versions refuse too. Other models routed to Anthropic answer 400 to temperature
    together with top_p, and to any temperature but 1 while thinking is on, so there top_p
    is dropped whenever temperature is sent or thinking is on, and temperature is dropped
    while thinking is on unless it is 1. Every other model gets every set param.

    Args:
        model: The model identity: `litellm_call_model(provider, model_name)` without a
            deployment id, never a deployment label.
        exclude: Generation fields the caller must not send (e.g. a client that sets its
            own stop sequences or timeout).
    """
    excluded = exclude or set()
    kwargs = {
        name: value
        for name, value in {**config.parameters, "timeout": config.timeout}.items()
        if name not in excluded and value is not None
    }
    if litellm_refuses_sampling(model):
        for name in SAMPLING_PARAMETERS:
            kwargs.pop(name, None)
    elif litellm_routed_provider(model) == _ANTHROPIC_PROVIDER:
        _drop_sampling_params_anthropic_rejects(kwargs)
    return kwargs


def _drop_sampling_params_anthropic_rejects(kwargs: dict) -> None:
    # litellm maps reasoning_effort "none" to no thinking block at all.
    thinking_enabled = kwargs.get("reasoning_effort", "none") != "none"
    if thinking_enabled and kwargs.get("temperature", 1) != 1:
        del kwargs["temperature"]
    if thinking_enabled or "temperature" in kwargs:
        kwargs.pop("top_p", None)


def _model_and_provider(model: str) -> tuple[str, str]:
    # A provider prefix is taken as is: for some providers (github_copilot, chatgpt)
    # get_llm_provider logs in, which blocks on a device-code prompt.
    provider, _, model_name = model.partition("/")
    if model_name and provider in litellm.provider_list:
        return model_name, provider
    model_name, provider, _, _ = litellm.get_llm_provider(model=model)
    return model_name, provider


def _mapped_params(model_name: str, provider: str, **sampling: float) -> dict:
    # drop_params=True: litellm leaves out what it refuses rather than raising.
    return litellm.utils.get_optional_params(
        model=model_name, custom_llm_provider=provider, drop_params=True, **sampling
    )
