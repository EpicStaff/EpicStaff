"""A stored config's `parameters` as a run sends them, refused when the model does not accept them.

Every payload that carries a config's settings to another service takes them from here.
A catalog update can lower a model's limit, drop a choice or drop a setting a config
stored; the run is then refused rather than sent something other than what the user set.
Only settings block: a deprecated model or a connection problem shows "needs review" and
still runs.
"""

from typing import Any

from tables.exceptions import ConfigNeedsReviewError

from ai_models.domain.specs import ModelKind
from ai_models.models import EmbeddingConfig, LLMConfig
from ai_models.services.config_validation import ConfigValidationService, parameters_to_send


def embedding_config_parameters(config: EmbeddingConfig) -> dict[str, Any]:
    """Return the embedding config's set settings; empty without a model or provider.

    Reads `config.model.embedding_provider`: select it with the config to avoid two queries.

    Raises:
        ConfigNeedsReviewError: A set setting is one the model does not accept.
    """
    provider = config.model.embedding_provider if config.model else None
    if provider is None:
        return {}
    return _run_parameters(ModelKind.EMBEDDING, "Embedding", provider.name, config)


def llm_config_parameters(config: LLMConfig) -> dict[str, Any]:
    """Return the LLM config's set settings; empty without a model or provider.

    Reads `config.model.llm_provider`: select it with the config to avoid two queries.

    Raises:
        ConfigNeedsReviewError: A set setting is one the model does not accept.
    """
    provider = config.model.llm_provider if config.model else None
    if provider is None:
        return {}
    return _run_parameters(ModelKind.LLM, "LLM", provider.name, config)


def _run_parameters(
    kind: ModelKind, label: str, provider: str, config: EmbeddingConfig | LLMConfig
) -> dict[str, Any]:
    parameters = parameters_to_send(config.parameters)
    problems = ConfigValidationService().parameter_problems(
        kind, provider, config.model.name, parameters
    )
    if problems:
        raise ConfigNeedsReviewError(label, config.custom_name, problems)
    return parameters
