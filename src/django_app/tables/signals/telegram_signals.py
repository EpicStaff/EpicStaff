from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from loguru import logger

from tables.models.graph_models import TelegramTriggerNode
from tables.models.webhook_models import WebhookTriggerAuthKind
from tables.services.recycle_bin.restoring import is_restoring
from tables.services.telegram_trigger_service import TelegramTriggerService
from tables.services.webhook_trigger_service import WebhookTriggerService
from tables.signals.webhook_signals import cleanup_orphaned_auth_if_unclaimed


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
        logger.exception(f"Error resyncing tunnel registration for TelegramTriggerNode ID: {id_}")


def _cleanup_orphaned_telegram_node_auth(trigger_id: int | None) -> None:
    cleanup_orphaned_auth_if_unclaimed(
        trigger_id,
        WebhookTriggerAuthKind.TELEGRAM,
        # all_objects: a binned node still claims the auth, so a restore can
        # register it again. Only a purge (post_delete) frees it.
        is_claimed=lambda: TelegramTriggerNode.all_objects.filter(
            webhook_trigger_id=trigger_id
        ).exists(),
    )


@receiver(pre_save, sender=TelegramTriggerNode)
def telegram_trigger_node_pre_save_handler(sender, instance: TelegramTriggerNode, **_):
    previous = None
    if instance.pk:
        previous = (
            TelegramTriggerNode.objects.filter(pk=instance.pk)
            .values_list("webhook_trigger_id", "telegram_bot_api_key_secret_id")
            .first()
        )
    (
        instance._previous_webhook_trigger_id,
        instance._previous_bot_api_key_secret_id,
    ) = previous or (None, None)


def _retire_webhook_after_commit(instance: TelegramTriggerNode) -> None:
    """Retire a binned or deleted node's bot webhook once the change has committed.

    After commit, so a rolled-back delete keeps the webhook, and a delete +
    recreate in one transaction (version restore, import replace) sees the
    recreated node still using the bot. Called before the orphaned-auth
    cleanup is queued, so it runs while the auth still exists.
    """
    TelegramTriggerService().retire_bot_webhook_after_commit(
        instance.webhook_trigger_id, instance.telegram_bot_api_key_secret_id, instance.pk
    )


def _register_restored_node(id_: int) -> None:
    """Register a restored node's bot once the restore has committed, if it's still live."""
    node = TelegramTriggerNode.objects.filter(pk=id_).first()
    if node is None:
        return
    _resync_tunnel_registration(id_)
    TelegramTriggerService().register_and_log(node)


@receiver(post_save, sender=TelegramTriggerNode)
def telegram_trigger_post_save_handler(sender, instance: TelegramTriggerNode, **kwargs):
    id_ = instance.pk
    logger.info("Triggered post_save signal for TelegramTriggerNode ID: {}", id_)

    if is_restoring(instance):
        # A restore only flips the soft-delete fields, so there's no old trigger to
        # clean up: registering is all that's left, and it waits for the commit.
        transaction.on_commit(lambda: _register_restored_node(id_))
        return

    _resync_tunnel_registration(id_)

    if not instance.active:
        _retire_webhook_after_commit(instance)
        _cleanup_orphaned_telegram_node_auth(instance.webhook_trigger_id)
        logger.info(f"TelegramTriggerNode {id_} is soft-deleted, skipping registration")
        return

    old_trigger_id = getattr(instance, "_previous_webhook_trigger_id", None)
    new_trigger_id = instance.webhook_trigger_id
    old_bot_api_key_secret_id = getattr(instance, "_previous_bot_api_key_secret_id", None)
    if (old_trigger_id, old_bot_api_key_secret_id) != (
        new_trigger_id,
        instance.telegram_bot_api_key_secret_id,
    ):
        # Before registering: registration overwrites the auth's record of the
        # URL the old bot was registered at, which retiring compares against.
        TelegramTriggerService().retire_bot_webhook_after_commit(
            old_trigger_id, old_bot_api_key_secret_id, id_
        )
    if old_trigger_id is not None and old_trigger_id != new_trigger_id:
        _cleanup_orphaned_telegram_node_auth(old_trigger_id)

    TelegramTriggerService().register_and_log(instance)


@receiver(post_delete, sender=TelegramTriggerNode)
def telegram_trigger_post_delete_handler(sender, instance: TelegramTriggerNode, **kwargs):
    logger.info(f"Triggered post_delete signal for TelegramTriggerNode ID: {instance.pk}")
    _resync_tunnel_registration(instance.pk)
    if instance.active:
        # A binned node's webhook was retired when it was binned.
        _retire_webhook_after_commit(instance)
    _cleanup_orphaned_telegram_node_auth(instance.webhook_trigger_id)
