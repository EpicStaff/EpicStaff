from __future__ import annotations

from ai_models.models import LLMConfig
from ai_models.utils.litellm_model_info import model_needs_prompt_cache_markers


def prompt_caching_available(*llm_configs: LLMConfig | None) -> bool:
    """Return True when an agent running these LLM configs can use prompt caching.

    Pass the agent's primary and fallback configs. The agent service sends cache markers
    only to a model that takes them, so caching needs one config whose model does; a
    config without a model takes none. Reads each config's model and its provider: load
    them together with the configs, or each costs two queries.
    """
    return any(model_needs_prompt_cache_markers(config.model) for config in llm_configs if config)
