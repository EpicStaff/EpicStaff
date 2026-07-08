from tables.models.base_models import BaseGlobalNode
from tables.models.llm_models import LLMConfig


def _yes_no(value: object) -> str:
    return "Yes" if value else "No"


def _format_mapping(mapping: dict | None) -> str:
    if not mapping:
        return ""
    return "\n".join(f"{key}: {value}" for key, value in mapping.items())


def _llm_config_label(config: LLMConfig | None) -> str:
    if config is None:
        return ""
    model_name = config.model.name if config.model else ""
    if model_name and model_name != config.custom_name:
        return f"{config.custom_name} ({model_name})"
    return config.custom_name


def _node_label(node_id: int | None, cache: dict[int, str]) -> str:
    if not node_id:
        return ""
    if node_id not in cache:
        target = BaseGlobalNode.find_globally(node_id)
        cache[node_id] = getattr(target, "node_name", "") or f"node #{node_id}"
    return cache[node_id]
