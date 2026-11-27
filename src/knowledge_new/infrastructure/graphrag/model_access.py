from graphrag_llm.config import ModelConfig
from src.shared.litellm_model_names import (
    litellm_call_model,
    litellm_generation_kwargs,
    litellm_routed_provider,
)
from src.shared.models.ai_providers import LLMConfigData

# GraphRAG never sends an LLM config's stop sequences: written for agents, they would cut
# extraction output short. Its timeout is not sent either: the 120 s default would abort
# long extraction and community-report calls.
_GRAPHRAG_EXCLUDED_GENERATION_FIELDS = {"stop"}


def completion_call_arguments(model_config: ModelConfig, parameters: dict) -> dict:
    """Return an LLM config's settings, as django_app sends them, as GraphRAG call arguments.

    Call it before `apply_request_access` rewrites the provider of `model_config`.
    """
    return litellm_generation_kwargs(
        LLMConfigData(model=model_config.model, parameters=parameters),
        model=litellm_call_model(model_config.model_provider, model_config.model),
        exclude=_GRAPHRAG_EXCLUDED_GENERATION_FIELDS,
    )


def apply_request_access(
    model_config: ModelConfig,
    *,
    api_key: str | None,
    extra_headers: dict[str, str],
    connection: dict[str, str],
    call_arguments: dict,
) -> None:
    """Complete `model_config`, as loaded from the database, with what a request supplies.

    `connection` holds the provider's connection arguments under their LiteLLM names, as
    django_app sends them (secrets resolved), and `call_arguments` the config's settings the
    model catalog allows. The model string follows `litellm_call_model`, so an Azure config
    calls its `deployment_id`. graphrag_llm builds every litellm call from
    `model_provider/model`, the key and endpoint fields, then spreads `call_args` over them,
    so the settings, the remaining connection arguments and the headers go there. Holds
    secrets once applied: never log `model_config`.
    """
    model = litellm_call_model(
        model_config.model_provider, model_config.model, connection.get("deployment_id")
    )
    provider = litellm_routed_provider(model)
    arguments = LLMConfigData(model=model, connection=connection).connection_kwargs()
    model_config.model_provider = provider
    model_config.model = model.removeprefix(f"{provider}/")
    model_config.api_key = api_key
    model_config.api_base = arguments.pop("api_base", None)
    model_config.api_version = arguments.pop("api_version", None)
    model_config.call_args = {**model_config.call_args, **call_arguments, **arguments}
    if extra_headers:
        model_config.call_args["extra_headers"] = dict(extra_headers)
