from loguru import logger
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from tables.services.telegram_trigger_service import TelegramTriggerService
from tables.services.webhook_trigger_service import WebhookTriggerService
from tables.models.graph_models import TelegramTriggerNode
from tables.models.webhook_models import WebhookTriggerAuth, WebhookTriggerAuthKind


def _resync_tunnel_registration(id_: int) -> None:
    """Re-push all tunnel configs to the `webhook` service.

    Both `WebhookTriggerNode` and `TelegramTriggerNode` now share the same
    bare-path tunnel registration (no prefix), so attaching/detaching a
    `TelegramTriggerNode` no longer changes the registered name itself.
    This resync is kept so a fresh `TelegramTriggerNode` attach always
    re-pushes the current tunnel configs before `register_telegram_trigger`
    reads the tunnel URL, avoiding a race against `webhook_signals`'s own
    post_save/post_delete registration on the config models.
    """
    try:
        registered = WebhookTriggerService().register_webhooks()
        if not registered:
            logger.error(
                f"Tunnel resync signal was sent but not delivered for TelegramTriggerNode ID: {id_}"
            )
    except Exception:
        logger.exception(
            f"Error resyncing tunnel registration for TelegramTriggerNode ID: {id_}"
        )


def _cleanup_orphaned_telegram_node_auth(trigger_id: int | None) -> None:
    if trigger_id is None:
        return
    if TelegramTriggerNode.objects.filter(webhook_trigger_id=trigger_id).exists():
        return
    WebhookTriggerAuth.objects.filter(
        trigger_id=trigger_id, kind=WebhookTriggerAuthKind.TELEGRAM
    ).delete()


@receiver(pre_save, sender=TelegramTriggerNode)
def telegram_trigger_node_pre_save_handler(sender, instance: TelegramTriggerNode, **_):
    if instance.pk:
        instance._previous_webhook_trigger_id = (
            TelegramTriggerNode.objects.filter(pk=instance.pk)
            .values_list("webhook_trigger_id", flat=True)
            .first()
        )
    else:
        instance._previous_webhook_trigger_id = None


@receiver(post_save, sender=TelegramTriggerNode)
def telegram_trigger_post_save_handler(sender, instance: TelegramTriggerNode, **kwargs):
    id_ = instance.pk
    logger.info(f"Triggered post_save signal for TelegramTriggerNode ID: {id_}")

    _resync_tunnel_registration(id_)

    old_trigger_id = getattr(instance, "_previous_webhook_trigger_id", None)
    new_trigger_id = instance.webhook_trigger_id
    if old_trigger_id is not None and old_trigger_id != new_trigger_id:
        _cleanup_orphaned_telegram_node_auth(old_trigger_id)

    try:
        TelegramTriggerService().register_telegram_trigger(
            telegram_trigger_instance=instance
        )
        logger.info(
            f"Successfully registered telegram trigger for TelegramTriggerNode : {id_}"
        )

    except Exception:
        logger.exception("Error registering telegram bot {id_}", id_=id_)


@receiver(post_delete, sender=TelegramTriggerNode)
def telegram_trigger_post_delete_handler(sender, instance: TelegramTriggerNode, **kwargs):
    logger.info(f"Triggered post_delete signal for TelegramTriggerNode ID: {instance.pk}")
    _resync_tunnel_registration(instance.pk)
    _cleanup_orphaned_telegram_node_auth(instance.webhook_trigger_id)
