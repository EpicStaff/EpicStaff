"""The single rule for turning an LLM config row into a litellm model name.

Used by the agent service, crew and django_app, so every service sends the same model
to the same provider. Imports litellm, so only import it from a service that has litellm.
"""

import litellm

__all__ = ["PROVIDER_ALIASES", "litellm_call_model", "litellm_lookup_name", "litellm_routed_provider"]

# Provider rows whose name is not a litellm provider, mapped to the litellm provider their
# stored model names are prefixed with (e.g. "google_ai" rows hold "gemini/gemini-flash-latest").
PROVIDER_ALIASES = {
    "google_ai": "gemini",
    "novita_ai": "novita",
    "aws_sagemaker": "sagemaker",
    "featherless-ai": "featherless_ai",
}

_AZURE_PROVIDERS = frozenset({"azure", "azure_openai"})


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
