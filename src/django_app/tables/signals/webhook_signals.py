from loguru import logger
from django.db import transaction
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
    model_name, pk = sender.__name__, instance.pk
    transaction.on_commit(lambda: _re_register_webhooks(model_name, pk))


@receiver(post_delete, sender=NgrokWebhookConfig)
@receiver(post_delete, sender=LocalhostWebhookConfig)
def webhook_config_post_delete_handler(sender, instance, **_):
    model_name, pk = sender.__name__, instance.pk
    transaction.on_commit(lambda: _re_register_webhooks(model_name, pk))


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

    Also fires when `TelegramTriggerService.register_telegram_trigger` calls
    `WebhookNodeAuth.objects.get_or_create(...)` to create a Telegram node's
    auth row -- that flow doesn't itself re-push tunnel config afterward, so
    this handler is what actually gets the freshly created/rotated Telegram
    credential into the running `webhook` service's registry.
    """
    model_name, pk = sender.__name__, instance.pk
    transaction.on_commit(lambda: _re_register_webhooks(model_name, pk))


@receiver(post_delete, sender=WebhookNodeAuth)
def webhook_node_auth_post_delete_handler(sender, instance: WebhookNodeAuth, **_):
    """Symmetric to the post_save handler above.

    In practice, clearing auth via `WebhookTriggerNodeSerializer._sync_
    webhook_node_auth` -> `WebhookTriggerService.disable_webhook_auth` does
    NOT delete this row -- it soft-disables it (`enabled=False`), which is
    already covered by the post_save handler above. This post_delete handler
    exists for the less common case where the row is actually removed (e.g.
    cascading delete of its parent trigger node, or a direct ORM/admin
    delete) -- it must still re-push so a removed credential doesn't stay
    live in the `webhook` service's registry after the DB row is gone.
    """
    model_name, pk = sender.__name__, instance.pk
    transaction.on_commit(lambda: _re_register_webhooks(model_name, pk))


@receiver(post_save, sender=WebhookTriggerNode)
def webhook_trigger_node_post_save_handler(
    sender, instance: WebhookTriggerNode, created: bool = False, **_
):
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

    On creation, this is also the single place that guarantees a
    `WebhookNodeAuth` row exists -- mirroring how `telegram_trigger_post_save_
    handler` unconditionally calls `register_telegram_trigger` (which itself
    `get_or_create`s the Telegram node's auth row) regardless of which code
    path created the `TelegramTriggerNode`. Every creation path for
    `WebhookTriggerNode` goes through the ORM's `.create()`/`.save()`, so
    firing here -- rather than only from `WebhookTriggerNodeSerializer.create()`
    -- also covers graph version restore (`graph_versioning/manager.py`),
    import/copy (`import_export/strategies/nodes/webhook_trigger_node.py`),
    in-DB copy (`copy_services/node_copy_handlers.py`), and Django admin.
    Gated on `created` (not fired on every save like the tunnel re-push
    above) because `ensure_webhook_auth(enabled=True)` would otherwise
    silently re-enable a credential an operator had explicitly disabled, on
    the next unrelated save of the node (e.g. a rename).
    """
    if created:
        try:
            WebhookTriggerService().ensure_webhook_auth(instance, enabled=True)
        except Exception:
            logger.exception(
                f"Error ensuring webhook_node_auth for WebhookTriggerNode ID: {instance.pk}"
            )

    model_name, pk = sender.__name__, instance.pk
    transaction.on_commit(lambda: _re_register_webhooks(model_name, pk))


@receiver(post_delete, sender=WebhookTriggerNode)
def webhook_trigger_node_post_delete_handler(sender, instance: WebhookTriggerNode, **_):
    """Symmetric to the post_save handler above: detaching (deleting) a
    `WebhookTriggerNode` must also re-push so its credentials don't stay live
    in the `webhook` service's registry after the DB row is gone.
    """
    model_name, pk = sender.__name__, instance.pk
    transaction.on_commit(lambda: _re_register_webhooks(model_name, pk))
