"""A stored config's `parameters` limited to the settings the model catalog allows now.

Every payload that carries a config's settings to another service takes them from here,
so a setting a catalog update no longer allows is never sent, and a value outside the
model's range is sent as the nearest limit.
"""

from typing import Any

from ai_models.domain.specs import ModelKind
from ai_models.models import EmbeddingConfig, LLMConfig
from ai_models.services.config_validation import ConfigValidationService


def embedding_config_parameters(config: EmbeddingConfig) -> dict[str, Any]:
    """Return the embedding config's settings a call may send; empty without a model or provider.

    Reads `config.model.embedding_provider`: select it with the config to avoid two queries.
    """
    provider = config.model.embedding_provider if config.model else None
    if provider is None:
        return {}
    return ConfigValidationService().allowed_parameters(
        ModelKind.EMBEDDING, provider.name, config.model.name, config.parameters
    )


def llm_config_parameters(config: LLMConfig) -> dict[str, Any]:
    """Return the LLM config's settings a call may send; empty without a model or provider.

    Reads `config.model.llm_provider`: select it with the config to avoid two queries.
    """
    provider = config.model.llm_provider if config.model else None
    if provider is None:
        return {}
    return ConfigValidationService().allowed_parameters(
        ModelKind.LLM, provider.name, config.model.name, config.parameters
    )
