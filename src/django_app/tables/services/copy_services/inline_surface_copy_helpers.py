from agents.services.surface_content_service import SurfaceContentModels, SurfaceContentService
from django.core.exceptions import ObjectDoesNotExist
from tables.models import AgentNode, AgentNodeTask


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
    SurfaceContentService.copy_content(
        source_surface, new_surface, content, org_id=new_node.graph.org_id
    )


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
