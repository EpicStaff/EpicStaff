"""
Shared import helpers for the AgentNode/TaskNode inline-surface data
(``AgentInlineSurface`` / ``InlineSurface``) and node-owned M2M/child rows
(``surface_list``, ``AgentNodeTask``).

Used by both ``AgentNodeStrategy`` and ``TaskNodeStrategy`` to avoid
duplicating the recreation logic across the two node types.
"""

from tables.models import AgentNode, AgentNodeTask
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper


def create_inline_surface(
    surface_model,
    owner_kwargs: dict,
    python_tool_model,
    mcp_tool_model,
    tool_fk_name: str,
    inline_surface_data: dict | None,
    id_mapper: IDMapper,
) -> None:
    if not inline_surface_data:
        return

    inline_surface = surface_model.objects.create(
        instructions=inline_surface_data.get("instructions", ""),
        **owner_kwargs,
    )

    tools = inline_surface_data.get("tools", {})

    python_rows = []
    for entry in tools.get(EntityType.PYTHON_CODE_TOOL, []):
        new_id = id_mapper.get_or_none(
            EntityType.PYTHON_CODE_TOOL, entry["python_tool_id"]
        )
        if new_id is None:
            continue

        python_rows.append(
            python_tool_model(
                **{tool_fk_name: inline_surface},
                python_tool_id=new_id,
                mode=entry["mode"],
            )
        )

    python_tool_model.objects.bulk_create(python_rows, ignore_conflicts=True)

    mcp_rows = []
    for entry in tools.get(EntityType.MCP_TOOL, []):
        new_id = id_mapper.get_or_none(EntityType.MCP_TOOL, entry["mcp_tool_id"])
        if new_id is None:
            continue

        mcp_rows.append(
            mcp_tool_model(
                **{tool_fk_name: inline_surface},
                mcp_tool_id=new_id,
                mode=entry["mode"],
            )
        )

    mcp_tool_model.objects.bulk_create(mcp_rows, ignore_conflicts=True)


def assign_node_surface_list(node, surface_ids: list, id_mapper: IDMapper) -> None:
    new_ids = []

    for old_id in surface_ids:
        new_id = id_mapper.get_or_none(EntityType.SURFACE, old_id)
        if new_id is not None:
            new_ids.append(new_id)

    node.surface_list.set(new_ids)


def create_agent_node_tasks(agent_node: AgentNode, tasks_data: list) -> None:
    old_to_new = {}

    for task_data in tasks_data:
        new_task = AgentNodeTask.objects.create(
            agent_node=agent_node,
            name=task_data["name"],
            order=task_data["order"],
            instructions=task_data.get("instructions", ""),
            output_schema=task_data.get("output_schema", {}),
        )
        old_to_new[task_data.get("id")] = new_task

    for task_data in tasks_data:
        new_task = old_to_new.get(task_data.get("id"))
        if new_task is None:
            continue

        context_tasks = [
            old_to_new[old_context_id]
            for old_context_id in task_data.get("context_tasks", [])
            if old_context_id in old_to_new
        ]
        if context_tasks:
            new_task.context_tasks.set(context_tasks)
