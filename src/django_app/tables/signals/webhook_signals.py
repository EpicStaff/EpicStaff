from loguru import logger
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from tables.services.webhook_trigger_service import WebhookTriggerService
from tables.models.webhook_models import (
    LocalhostWebhookConfig,
    NgrokWebhookConfig,
    WebhookNodeAuth,
)
from tables.models.graph_models import WebhookTriggerNode


def _re_register_webhooks(model_name: str, id_: int) -> None:
    logger.info(f"Triggered webhook re-registration for {model_name} ID: {id_}")
    try:
        registered = WebhookTriggerService().register_webhooks()
        if registered:
            logger.info("Successfully registered webhooks")
        else:
            logger.error("Register signal was sent but not delivered")
    except Exception:
        logger.exception(f"Error registering webhooks for {model_name} ID: {id_}")


@receiver(post_save, sender=NgrokWebhookConfig)
@receiver(post_save, sender=LocalhostWebhookConfig)
def webhook_config_post_save_handler(sender, instance, **_):
    _re_register_webhooks(sender.__name__, instance.pk)


@receiver(post_delete, sender=NgrokWebhookConfig)
@receiver(post_delete, sender=LocalhostWebhookConfig)
def webhook_config_post_delete_handler(sender, instance, **_):
    _re_register_webhooks(sender.__name__, instance.pk)


@receiver(post_save, sender=WebhookNodeAuth)
def webhook_node_auth_post_save_handler(sender, instance: WebhookNodeAuth, **_):
    """`WebhookTriggerNodeSerializer._sync_webhook_node_auth` (create/update
    path) persists this row directly via the ORM -- no re-push to the
    `webhook` service on its own -- so a freshly enabled/edited credential
    never reaches the running service's cached `TunnelRegistry` state until
    something unrelated happens to trigger one. Mirrors
    `webhook_config_post_save_handler` above: `register_webhooks()` rebuilds
    the full config from scratch on every call (see its `_TRIGGER_NODE_
    PREFETCHES`-based query), so this is safe to fire unconditionally for
    BOTH attachment types.

    Also fires when `TelegramTriggerService._ensure_telegram_webhook_node_
    auth` creates a Telegram node's auth row -- that flow already calls
    `register_webhooks()` explicitly (before `setWebhook`, with a rollback
    path on failure), so this adds a harmless redundant push, not a
    conflicting one; it never touches `TelegramTriggerNode`/`WebhookTrigger
    Node` itself so it cannot interfere with that flow's own atomic
    create/rollback transaction.
    """
    _re_register_webhooks(sender.__name__, instance.pk)


@receiver(post_delete, sender=WebhookNodeAuth)
def webhook_node_auth_post_delete_handler(sender, instance: WebhookNodeAuth, **_):
    """Symmetric to the post_save handler above: `_sync_webhook_node_auth`
    deletes this row when auth is explicitly cleared (falsy `auth_data`), and
    `TelegramTriggerService._rollback_new_telegram_webhook_node_auth` deletes
    it on a failed registration attempt -- both must re-push so a
    disabled/rolled-back credential doesn't stay live in the `webhook`
    service's registry after the DB row is gone.
    """
    _re_register_webhooks(sender.__name__, instance.pk)


@receiver(post_save, sender=WebhookTriggerNode)
def webhook_trigger_node_post_save_handler(sender, instance: WebhookTriggerNode, **_):
    """A `WebhookTriggerNode` can be attached to (re-pointed at) an existing
    `WebhookTrigger` -- or have its `webhook_trigger` FK cleared -- after that
    trigger's tunnel config was already registered once. Nothing else
    re-pushes the config in that case, so the running `webhook` service keeps
    serving a stale credential list that doesn't reflect this node's
    `webhook_node_auth` (see `webhook_node_auth_post_save_handler` above; and
    `telegram_trigger_post_save_handler` in `telegram_signals.py`, the exact
    equivalent for `TelegramTriggerNode`). `register_webhooks()` rebuilds the
    full config from scratch on every call, so firing this unconditionally on
    every save is harmless, not just on FK changes.
    """
    _re_register_webhooks(sender.__name__, instance.pk)


@receiver(post_delete, sender=WebhookTriggerNode)
def webhook_trigger_node_post_delete_handler(sender, instance: WebhookTriggerNode, **_):
    """Symmetric to the post_save handler above: detaching (deleting) a
    `WebhookTriggerNode` must also re-push so its credentials don't stay live
    in the `webhook` service's registry after the DB row is gone.
    """
    _re_register_webhooks(sender.__name__, instance.pk)
