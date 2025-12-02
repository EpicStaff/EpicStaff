from django.db.models.signals import m2m_changed, post_delete
from django.dispatch import receiver
from tables.models import Crew, Task, CrewNode
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


@receiver(post_delete, sender=CrewNode)
def delete_related_crew(sender, instance, **kwargs):
    """
    When CrewNode is deleted, also delete the associated Crew.
    """
    if instance.crew:
        instance.crew.delete()
