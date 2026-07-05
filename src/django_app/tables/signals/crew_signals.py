from django.db import transaction
from django.db.models.signals import m2m_changed, pre_delete
from django.dispatch import receiver
from tables.graph_collab.notifications import GraphEditNotifier
from tables.models import Crew, Task
from tables.models.graph_models import CrewNode
from loguru import logger


@receiver(m2m_changed, sender=Crew.agents.through)
def handle_crew_agents_change(sender, instance, action, pk_set, **kwargs):
    """
    Handle changes to the Crew.agents many-to-many relationship.
    When agents are removed from a crew, set their assigned tasks' agent field to None.
    """
    if action == "post_remove":
        # pk_set of agents that were removed
        removed_agent_ids = pk_set

        if removed_agent_ids:
            # Find all tasks belonging to this crew that were assigned to the removed agents
            tasks_to_update = Task.objects.filter(
                crew=instance, agent_id__in=removed_agent_ids
            )

            updated_count = tasks_to_update.update(agent=None)

            if updated_count > 0:
                logger.info(
                    f"Updated {updated_count} tasks for crew '{instance.name}' "
                    f"after removing agents: {removed_agent_ids}"
                )


@receiver(pre_delete, sender=Crew)
def handle_crew_pre_delete(sender, instance, **kwargs):
    """
    Capture (graph_id, crew_node_id) pairs before CASCADE removes the CrewNode
    rows, then broadcast nodes_deleted per affected graph once the delete
    transaction commits.

    Must be pre_delete, not post_delete: by post_delete time the cascade has
    already removed the CrewNode rows, so there is nothing left to look up.
    Deferred via transaction.on_commit so a rolled-back delete never messages
    live editors about a node that, in the end, was never actually removed.
    """
    pairs = list(
        CrewNode.objects.filter(crew_id=instance.pk).values_list("graph_id", "id")
    )
    if not pairs:
        return

    node_ids_by_graph: dict[int, list[int]] = {}
    for graph_id, node_id in pairs:
        node_ids_by_graph.setdefault(graph_id, []).append(node_id)

    def _broadcast():
        for graph_id, node_ids in node_ids_by_graph.items():
            try:
                GraphEditNotifier.broadcast_nodes_deleted(graph_id, node_ids)
            except Exception as exc:
                logger.error(
                    "Failed to broadcast crew deletion for graph {}: {}", graph_id, exc
                )

    transaction.on_commit(_broadcast)
