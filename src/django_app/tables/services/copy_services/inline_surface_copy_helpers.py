from django.core.exceptions import ObjectDoesNotExist

from agents.services.surface_content_service import SurfaceContentModels
from tables.models import AgentNode, AgentNodeTask

# SurfaceKnowledge's three optional one-to-one search configs use the same
# related_name on every inline-surface family; `content_attr` picks the
# matching model class off the SurfaceContentModels bundle.
_SEARCH_CONFIG_RELATED_NAMES = (
    ("naive_search_config", "naive_config"),
    ("graph_basic_search_config", "graph_basic_config"),
    ("graph_local_search_config", "graph_local_config"),
)


def _copy_field_values(instance, exclude: set[str]) -> dict:
    """Return {field_name: value} for concrete, non-pk fields not in `exclude`."""
    return {
        field.name: getattr(instance, field.name)
        for field in instance._meta.concrete_fields
        if not field.primary_key and field.name not in exclude
    }


def copy_node_inline_surface(
    source_node,
    new_node,
    surface_model,
    node_fk_name: str,
    content: SurfaceContentModels,
) -> None:
    """Deep-copy a TaskNode/AgentNode inline surface and its content rows.

    Shared by both inline-surface families (InlineSurface + AgentInlineSurface):
    their content model layout is identical, only the model classes and FK
    names differ, which are bundled in `surface_model` / `content`.
    """
    try:
        source_surface = source_node.inline_surface
    except ObjectDoesNotExist:
        return

    new_surface = surface_model.objects.create(
        instructions=source_surface.instructions,
        **{node_fk_name: new_node},
    )

    source_owner = {content.parent_field: source_surface}
    new_owner = {content.parent_field: new_surface}

    for tool in content.python_tool.objects.filter(**source_owner):
        content.python_tool.objects.create(
            python_tool=tool.python_tool, mode=tool.mode, **new_owner
        )

    for tool in content.mcp_tool.objects.filter(**source_owner):
        content.mcp_tool.objects.create(
            mcp_tool=tool.mcp_tool, mode=tool.mode, **new_owner
        )

    for item in content.storage_item.objects.filter(**source_owner):
        content.storage_item.objects.create(
            storage_file=item.storage_file,
            can_list=item.can_list,
            can_view=item.can_view,
            can_edit=item.can_edit,
            can_delete=item.can_delete,
            **new_owner,
        )

    for knowledge in content.knowledge.objects.filter(**source_owner):
        new_knowledge = content.knowledge.objects.create(
            collection=knowledge.collection, **new_owner
        )
        _copy_knowledge_search_configs(knowledge, new_knowledge, content)


def _copy_knowledge_search_configs(
    source_knowledge, new_knowledge, content: SurfaceContentModels
) -> None:
    for related_name, content_attr in _SEARCH_CONFIG_RELATED_NAMES:
        try:
            config = getattr(source_knowledge, related_name)
        except ObjectDoesNotExist:
            continue

        config_model = getattr(content, content_attr)
        values = _copy_field_values(config, exclude={"surface_knowledge"})
        config_model.objects.create(surface_knowledge=new_knowledge, **values)


def copy_agent_node_tasks(source_node: AgentNode, new_node: AgentNode) -> None:
    """Recreate AgentNodeTask children, remapping context_tasks old id -> new task."""
    old_id_to_new_task: dict[int, AgentNodeTask] = {}

    for task in source_node.tasks.all():
        new_task = AgentNodeTask.objects.create(
            agent_node=new_node,
            name=task.name,
            order=task.order,
            instructions=task.instructions,
            output_schema=task.output_schema,
        )
        old_id_to_new_task[task.id] = new_task

    for task in source_node.tasks.all():
        new_task = old_id_to_new_task[task.id]
        context_task_ids = task.context_tasks.values_list("id", flat=True)
        new_context_tasks = [
            old_id_to_new_task[context_task_id] for context_task_id in context_task_ids
        ]

        if new_context_tasks:
            new_task.context_tasks.set(new_context_tasks)
