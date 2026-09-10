from loguru import logger

from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.version_conversions.base import VersionConverter
from tables.models import McpTool, PythonCodeTool

_GENERIC_CONFIG_ENTITY_TYPES = (
    EntityType.LLM_CONFIG,
    EntityType.EMBEDDING_CONFIG,
    EntityType.REALTIME_CONFIG,
    EntityType.REALTIME_TRANSCRIPTION_CONFIG,
)


_ENTITY_TYPE_FALLBACK_MODELS = {
    EntityType.MCP_TOOL: McpTool,
    EntityType.PYTHON_CODE_TOOL: PythonCodeTool,
}


_ENTITY_TYPE_EXTRA_ALLOWED_FIELDS = {
    EntityType.PYTHON_CODE_TOOL: {"python_code", "python_code_tool_config"},
}

_STALE_FIELD_STRIPPED_ENTITY_TYPES = _GENERIC_CONFIG_ENTITY_TYPES + (
    EntityType.MCP_TOOL,
    EntityType.PYTHON_CODE_TOOL,
)


@VersionConverter.register(from_version=2)
def v2_to_v3(data: dict) -> dict:
    """
    v2 → v3:
    - PythonNode.stream_config stripped (removed from the model).
    - ClassificationConditionGroup.prompt_id remapped to the prompt FK id.
    - Stale fields stripped from *Config/MCPTool/PythonCodeTool entries that
      would otherwise crash find_existing() during import.
    - Deprecated nodes are ignored
    """
    for graph in data.get(EntityType.GRAPH, []):
        nodes = graph.get("nodes", [])
        _strip_python_node_stream_config(nodes)
        _remap_classification_prompt_refs(nodes)

    _merge_legacy_llm_config_headers(data)
    _strip_stale_config_fields(data)

    return data


def _merge_legacy_llm_config_headers(data: dict) -> None:
    for config in data.get(EntityType.LLM_CONFIG, []):
        legacy = config.pop("headers", None)
        if legacy:
            config["extra_headers"] = {**legacy, **(config.get("extra_headers") or {})}


def _strip_stale_config_fields(data: dict) -> None:
    for entity_type in _STALE_FIELD_STRIPPED_ENTITY_TYPES:
        configs = data.get(entity_type, [])
        if not configs:
            continue

        strategy = entity_registry.get_strategy(entity_type)
        model = (
            getattr(strategy, "config_model", None)
            or _ENTITY_TYPE_FALLBACK_MODELS[entity_type]
        )
        valid_fields = {
            field.name
            for field in model._meta.get_fields()
            if field.concrete or (field.many_to_many and not field.auto_created)
        } | _ENTITY_TYPE_EXTRA_ALLOWED_FIELDS.get(entity_type, set())

        for config in configs:
            for key in list(config.keys()):
                if key not in valid_fields:
                    config.pop(key)
                    logger.warning(
                        "Dropping stale field {} from legacy {} id={} during "
                        "v2->v3 conversion: field no longer exists on the "
                        "current model",
                        key,
                        entity_type,
                        config.get("id"),
                    )


def _strip_python_node_stream_config(nodes: list) -> None:
    for node in nodes:
        if node.get("node_type") == "PythonNode":
            node.pop("stream_config", None)


def _remap_classification_prompt_refs(nodes: list) -> None:
    for node in nodes:
        if node.get("node_type") != "ClassificationDecisionTableNode":
            continue

        # Legacy prompt_configs have no "id" — prompt_key is the only unique
        # identifier per node, so backfill id from it before resolving.
        for prompt_config in node.get("prompt_configs", []):
            if "prompt_key" not in prompt_config:
                logger.warning(
                    "prompt_configs entry missing prompt_key during v2->v3 "
                    "conversion: id will backfill to None"
                )
            prompt_config.setdefault("id", prompt_config.get("prompt_key"))

        prompt_key_to_id = {
            prompt_config.get("prompt_key"): prompt_config.get("id")
            for prompt_config in node.get("prompt_configs", [])
        }

        for group in node.get("condition_groups", []):
            if "prompt_id" not in group:
                continue

            prompt_key = group.pop("prompt_id")
            resolved_id = prompt_key_to_id.get(prompt_key)
            if resolved_id is None:
                logger.warning(
                    "Dangling prompt_id={} on ClassificationConditionGroup during "
                    "v2->v3 conversion: no matching prompt_key in prompt_configs",
                    prompt_key,
                )
            group["prompt"] = resolved_id
