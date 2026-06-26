from src.shared.models import LLMData
from src.crew.utils.llm_wrapper import PatchedLLM, _NO_TEMPERATURE_PATTERNS


def _strip_unsupported_params(llm_config: dict) -> dict:
    model = (llm_config.get("model") or "").lower()
    if any(p in model for p in _NO_TEMPERATURE_PATTERNS):
        llm_config.pop("temperature", None)
        llm_config.pop("top_p", None)
    return llm_config


def parse_llm(llm: LLMData, **kwargs):
    llm_config = {**llm.config.model_dump()}
    llm_config.update(kwargs)
    return PatchedLLM(**llm_config)


def parse_memory_llm(memory_llm: LLMData):
    memory_llm = memory_llm.model_dump()
    provider = memory_llm.get("provider")
    config = memory_llm.get("config")
    model = config.get("model")
    api_key = config.get("api_key")
    max_tokens = config.get("max_tokens")
    inner = {
        "model": model,
        "temperature": 0.0,
        "api_key": api_key,
        "max_tokens": max_tokens,
    }
    memory_llm_config = {
        "llm": {
            "provider": provider,
            "config": _strip_unsupported_params(inner),
        }
    }
    return memory_llm_config


def parse_memory_embedder(memory_embedder):
    # TODO: add dims (can be cause of bugs)
    memory_embedder = memory_embedder.model_dump()
    provider = memory_embedder.get("provider")
    config = memory_embedder.get("config")
    model = config.get("model")
    api_key = config.get("api_key")
    memory_embedder_config = {
        "embedder": {
            "provider": provider,
            "config": {"model": model, "api_key": api_key},
        }
    }
    return memory_embedder_config
