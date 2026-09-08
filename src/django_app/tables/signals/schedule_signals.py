from loguru import logger
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from django_app.settings import SCHEDULE_CHANNEL
from src.shared.models import (
    ScheduleTriggerNodeDeletePayload,
    ScheduleTriggerNodePayload,
    ScheduleTriggerNodeUpdateData,
    ScheduleTriggerNodeUpdateMessage,
)
from tables.models.graph_models import ScheduleTriggerNode
from tables.services.redis_service import RedisService


def _publish(message: ScheduleTriggerNodeUpdateMessage) -> None:
    RedisService().redis_client.publish(SCHEDULE_CHANNEL, message.model_dump_json())


@receiver(post_save, sender=ScheduleTriggerNode)
def schedule_trigger_post_save_handler(
    sender, instance: ScheduleTriggerNode, created, **kwargs
):
    """Publish a create/update event to the Manager on every node save."""
    node_id = instance.pk
    action = "create" if created else "update"
    logger.info(f"[ScheduleSignal] post_save triggered for node ID: {node_id}")

    try:
        node_payload = ScheduleTriggerNodePayload.model_validate(instance).model_copy(
            update={
                "is_active": instance.is_active
                and not getattr(instance, "is_soft_deleted", False)
            }
        )
        message = ScheduleTriggerNodeUpdateMessage(
            data=ScheduleTriggerNodeUpdateData(
                action=action,
                node=node_payload,
            )
        )
        _publish(message)
        logger.info(f"[ScheduleSignal] Published '{action}' for node ID: {node_id}")
    except Exception:
        logger.exception(
            f"[ScheduleSignal] Error publishing save event for node {node_id}"
        )


@receiver(post_delete, sender=ScheduleTriggerNode)
def schedule_trigger_post_delete_handler(
    sender, instance: ScheduleTriggerNode, **kwargs
):
    """Publish a delete event to the Manager on every node delete."""
    node_id = instance.pk
    logger.info(f"[ScheduleSignal] post_delete triggered for node ID: {node_id}")

    try:
        message = ScheduleTriggerNodeUpdateMessage(
            data=ScheduleTriggerNodeUpdateData(
                action="delete",
                node=ScheduleTriggerNodeDeletePayload(id=node_id),
            )
        )
        _publish(message)
        logger.info(f"[ScheduleSignal] Published 'delete' for node ID: {node_id}")
    except Exception:
        logger.exception(
            f"[ScheduleSignal] Error publishing delete event for node {node_id}"
        )
