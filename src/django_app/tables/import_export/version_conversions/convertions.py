from loguru import logger

from src.shared.models import args_schema_to_variables
from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.version_conversions.base import VersionConverter

_FIELD_TYPE_TO_VAR_TYPE = {
    "llm_config": "number",
    "embedding_config": "number",
    "string": "string",
    "boolean": "boolean",
    "any": "any",
    "integer": "number",
    "float": "number",
}


@VersionConverter.register(from_version=1)
def v1_to_v2(data: dict) -> dict:
    """
    v1 → v2: collapse args_schema + python_code_tool_config_fields into a
    single `variables` list, mirroring DB migration 0170. "integer" is
    normalized to "number" since VariableType has no integer variant.
    """
    for tool in data.get("PythonCodeTool", []):
        variables = args_schema_to_variables(tool.get("args_schema") or {})

        for field in tool.get("python_code_tool_config_fields", []):
            variables.append(
                {
                    "name": field.get("name"),
                    "type": _FIELD_TYPE_TO_VAR_TYPE.get(
                        field.get("data_type"), "string"
                    ),
                    "description": field.get("description") or "",
                    "default_value": None,
                    "input_type": "user_input",
                    "required": field.get("required", True),
                }
            )

        tool["variables"] = variables
        tool.pop("args_schema", None)
        tool.pop("python_code_tool_config_fields", None)

    return data


_AGENT_DIRECT_FIELDS = (
    "llm_config",
    "fcm_llm_config",
    "max_iter",
    "max_rpm",
    "max_execution_time",
    "cache",
    "max_retry_limit",
    "default_temperature",
)

_AGENT_DROPPED_FIELDS = (
    "memory",
    "allow_delegation",
    "allow_code_execution",
    "respect_context_window",
    "knowledge_collection",
)

_TASK_DROPPED_FIELDS = (
    "knowledge_query",
    "human_input",
    "async_execution",
    "config",
)

# These strategies' find_existing() uses every dict key as a literal ORM
# filter with no field validation, so a stale key raises FieldError. Provider
# realtime configs use a different base that only filters on
# custom_name/model_name and aren't affected.
_GENERIC_CONFIG_ENTITY_TYPES = (
    EntityType.LLM_CONFIG,
    EntityType.EMBEDDING_CONFIG,
    EntityType.REALTIME_CONFIG,
    EntityType.REALTIME_TRANSCRIPTION_CONFIG,
)


@VersionConverter.register(from_version=2)
def v2_to_v3(data: dict) -> dict:
    """
    v2 → v3: restore compatibility with 1.1.2 exports after the
    feat/crewai-removal refactor changed the flow node schema without
    bumping IMPORT_VERSION.

    - Trivial CrewNode -> AgentNode conversion, with a synthesized
      AgentDefinition. Non-trivial CrewNode/CodeAgentNode are left for the
      importer's unsupported-node-type skip path.
    - PythonNode.stream_config stripped (removed from the model).
    - ClassificationConditionGroup.prompt_id remapped to the prompt FK id.
    - Stale fields stripped from *Config entries that would otherwise crash
      find_existing() during import.
    """
    agent_definitions_by_source_id: dict = {}

    for graph in data.get(EntityType.GRAPH, []):
        nodes = graph.get("nodes", [])
        _convert_crew_nodes_in_graph(nodes, data, agent_definitions_by_source_id)
        _strip_python_node_stream_config(nodes)
        _remap_classification_prompt_refs(nodes)

    _strip_stale_config_fields(data)

    return data


def _convert_crew_nodes_in_graph(
    nodes: list, data: dict, agent_definitions_by_source_id: dict
) -> None:
    crews_by_id = {crew.get("id"): crew for crew in data.get(EntityType.CREW, [])}

    for index, node in enumerate(nodes):
        if node.get("node_type") != "CrewNode":
            continue

        crew = crews_by_id.get(node.get("crew"))
        if crew is None:
            logger.warning(
                "CrewNode id={} references missing crew id={} during "
                "v2->v3 conversion: leaving node unconverted",
                node.get("id"),
                node.get("crew"),
            )
            continue
        if not _is_trivial_crew(crew):
            continue

        nodes[index] = _convert_crew_node_to_agent_node(
            node, crew, agent_definitions_by_source_id, data
        )


def _is_trivial_crew(crew: dict) -> bool:
    """
    A crew is trivial (safely convertible to a plain AgentNode) only if none
    of its orchestration features are actually enabled. Leftover/default
    values in `manager_llm_config`, `planning_llm_config`, `memory_llm_config`,
    or `embedding_config` don't disqualify a crew on their own — those fields
    only take effect when their governing flag (`process`, `planning`,
    `memory`) is actually on.
    """
    agent_ids = {
        task.get("agent")
        for task in crew.get("tasks", [])
        if task.get("agent") is not None
    }
    if len(agent_ids) > 1:
        return False

    if crew.get("process", "sequential") != "sequential":
        return False

    if crew.get("planning"):
        return False

    if crew.get("memory"):
        return False

    return True


def _convert_crew_node_to_agent_node(
    node: dict, crew: dict, agent_definitions_by_source_id: dict, data: dict
) -> dict:
    node_id = node.get("id")
    tasks = crew.get("tasks", [])
    agent_ids = [task.get("agent") for task in tasks if task.get("agent") is not None]
    source_agent_id = agent_ids[0] if agent_ids else None

    agent_definition_id = None
    if source_agent_id is not None:
        if source_agent_id not in agent_definitions_by_source_id:
            agents_by_id = {
                agent.get("id"): agent for agent in data.get(EntityType.AGENT, [])
            }
            agent = agents_by_id.get(source_agent_id)
            if agent is not None:
                agent_definition = _agent_to_agent_definition_dict(agent)
                data.setdefault(EntityType.AGENT_DEFINITION, []).append(
                    agent_definition
                )
                agent_definitions_by_source_id[source_agent_id] = agent_definition["id"]
            else:
                logger.warning(
                    "CrewNode id={} references missing agent id={} during "
                    "v2->v3 conversion: resulting AgentNode will have "
                    "agent_definition=None",
                    node_id,
                    source_agent_id,
                )
        agent_definition_id = agent_definitions_by_source_id.get(source_agent_id)

    return {
        "id": node_id,
        "node_type": "AgentNode",
        "graph": node.get("graph"),
        "node_name": node.get("node_name"),
        "input_map": node.get("input_map"),
        "output_variable_path": node.get("output_variable_path"),
        "metadata": node.get("metadata"),
        "agent_definition": agent_definition_id,
        "surface_list": [],
        "inline_surface": None,
        "tasks": _crew_tasks_to_agent_node_tasks(tasks),
    }


def _agent_to_agent_definition_dict(agent: dict) -> dict:
    agent_id = agent.get("id")

    goal = agent.get("goal") or ""
    backstory = agent.get("backstory") or ""
    instructions = "\n\n".join(part for part in (goal, backstory) if part)

    agent_definition = {
        "id": agent_id,
        "name": f"legacy-agent-{agent_id}",
        "description": agent.get("role") or "",
        "instructions": instructions,
        "metadata": {},
        "owned_surfaces": [],
        "default_surfaces": [],
    }
    for field in _AGENT_DIRECT_FIELDS:
        agent_definition[field] = agent.get(field)

    tools = agent.get("tools") or {}
    if any(tools.get(key) for key in tools):
        logger.warning(
            "Dropping tools from legacy Agent id={} during v2->v3 conversion: "
            "AgentDefinition has no tools field",
            agent_id,
        )
    if agent.get("realtime_agent"):
        logger.warning(
            "Dropping realtime_agent from legacy Agent id={} during v2->v3 "
            "conversion: AgentDefinition has no realtime_agent field",
            agent_id,
        )
    if agent.get("naive_search_config"):
        logger.warning(
            "Dropping naive_search_config from legacy Agent id={} during v2->v3 "
            "conversion: AgentDefinition has no naive_search_config field",
            agent_id,
        )
    for field in _AGENT_DROPPED_FIELDS:
        if agent.get(field):
            logger.warning(
                "Dropping {} from legacy Agent id={} during v2->v3 conversion: "
                "AgentDefinition has no {} field",
                field,
                agent_id,
                field,
            )

    return agent_definition


def _crew_tasks_to_agent_node_tasks(tasks: list) -> list:
    ordered_tasks = sorted(
        enumerate(tasks),
        key=lambda pair: pair[1].get("order")
        if pair[1].get("order") is not None
        else pair[0],
    )

    # AgentNodeTask.order must be dense/unique (NOT NULL); the old Task.order
    # was nullable, so we recompute from sorted position rather than reuse it.
    id_to_final_order = {
        task.get("id"): position for position, (_, task) in enumerate(ordered_tasks)
    }

    all_original_names = {task.get("name") for _, task in ordered_tasks}

    agent_node_tasks = []
    used_names: set = set()
    next_suffix_by_name: dict = {}
    for position, (_, task) in enumerate(ordered_tasks):
        task_id = task.get("id")
        order = position

        original_name = task.get("name")
        if original_name not in used_names:
            name = original_name
        else:
            suffix = next_suffix_by_name.get(original_name, 2)
            candidate = f"{original_name} ({suffix})"
            while candidate in used_names or candidate in all_original_names:
                suffix += 1
                candidate = f"{original_name} ({suffix})"
            name = candidate
            next_suffix_by_name[original_name] = suffix + 1
            logger.warning(
                "Disambiguating duplicate legacy Task name {} (id={}) to {} "
                "during v2->v3 conversion: AgentNodeTask requires unique "
                "names within a node",
                original_name,
                task_id,
                name,
            )
        used_names.add(name)

        instructions = task.get("instructions") or ""
        expected_output = task.get("expected_output")
        if expected_output:
            instructions = f"{instructions}\n\nExpected output: {expected_output}"

        context_tasks = []
        for context_id in task.get("context", []):
            context_order = id_to_final_order.get(context_id)
            if context_order is None or context_order >= order:
                logger.warning(
                    "Dropping invalid context_tasks reference {} from legacy "
                    "Task id={} during v2->v3 conversion: referenced task's "
                    "resolved order is not strictly lower",
                    context_id,
                    task_id,
                )
                continue
            context_tasks.append(context_id)

        agent_node_tasks.append(
            {
                "id": task_id,
                "name": name,
                "order": order,
                "instructions": instructions,
                "output_schema": task.get("output_model") or {},
                "context_tasks": context_tasks,
            }
        )

        for field in _TASK_DROPPED_FIELDS:
            if task.get(field):
                logger.warning(
                    "Dropping {} from legacy Task id={} during v2->v3 conversion: "
                    "AgentNodeTask has no {} field",
                    field,
                    task_id,
                    field,
                )

    return agent_node_tasks


def _strip_stale_config_fields(data: dict) -> None:
    # Safe as a separate top-level pass: no node conversion above reads LLMConfig/EmbeddingConfig/RealtimeConfig/RealtimeTranscriptionConfig data.
    for entity_type in _GENERIC_CONFIG_ENTITY_TYPES:
        configs = data.get(entity_type, [])
        if not configs:
            continue

        model = entity_registry.get_strategy(entity_type).config_model
        valid_fields = {
            field.name
            for field in model._meta.get_fields()
            if field.concrete or (field.many_to_many and not field.auto_created)
        }

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
