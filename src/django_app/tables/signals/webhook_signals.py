from loguru import logger
from django.db import transaction
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver

from tables.services.webhook_trigger_service import WebhookTriggerService
from tables.models.webhook_models import (
    LocalhostWebhookConfig,
    NgrokWebhookConfig,
    TwilioChannel,
    WebhookTriggerAuth,
    WebhookTriggerAuthKind,
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


@receiver(post_save, sender=WebhookTriggerAuth)
def webhook_trigger_auth_post_save_handler(sender, instance: WebhookTriggerAuth, **_):
    """`WebhookTriggerService.set_webhook_trigger_auth` (webhook-kind, via the
    API) and `TelegramTriggerService.register_telegram_trigger`
    (telegram-kind) both persist this row directly via the ORM -- no re-push
    to the `webhook` service on their own -- so a freshly set/rotated
    credential never reaches the running service's cached `TunnelRegistry`
    state until something unrelated happens to trigger one.
    `register_webhooks()` rebuilds the full config from scratch on every
    call, so firing this unconditionally is safe.
    """
    model_name, pk = sender.__name__, instance.pk
    transaction.on_commit(lambda: _re_register_webhooks(model_name, pk))


@receiver(post_delete, sender=WebhookTriggerAuth)
def webhook_trigger_auth_post_delete_handler(sender, instance: WebhookTriggerAuth, **_):
    """Symmetric to the post_save handler above -- a removed credential (e.g.
    cascading delete of its parent `WebhookTrigger`) must not stay live in
    the `webhook` service's registry after the DB row is gone.
    """
    model_name, pk = sender.__name__, instance.pk
    transaction.on_commit(lambda: _re_register_webhooks(model_name, pk))


@receiver(pre_save, sender=WebhookTriggerNode)
def webhook_trigger_node_pre_save_handler(sender, instance: WebhookTriggerNode, **_):
    if instance.pk:
        instance._previous_webhook_trigger_id = (
            WebhookTriggerNode.objects.filter(pk=instance.pk)
            .values_list("webhook_trigger_id", flat=True)
            .first()
        )
    else:
        instance._previous_webhook_trigger_id = None


@receiver(post_save, sender=WebhookTriggerNode)
def webhook_trigger_node_post_save_handler(
    sender, instance: WebhookTriggerNode, created: bool = False, **_
):

    model_name, pk = sender.__name__, instance.pk
    transaction.on_commit(lambda: _re_register_webhooks(model_name, pk))

    old_trigger_id = getattr(instance, "_previous_webhook_trigger_id", None)
    new_trigger_id = instance.webhook_trigger_id
    if old_trigger_id is not None and old_trigger_id != new_trigger_id:
        _cleanup_orphaned_webhook_node_auth(old_trigger_id)


@receiver(post_delete, sender=WebhookTriggerNode)
def webhook_trigger_node_post_delete_handler(sender, instance: WebhookTriggerNode, **_):
    """Symmetric to the post_save handler above: detaching (deleting) a
    `WebhookTriggerNode` must also re-push so its credentials don't stay live
    in the `webhook` service's registry after the DB row is gone.
    """
    model_name, pk = sender.__name__, instance.pk
    transaction.on_commit(lambda: _re_register_webhooks(model_name, pk))

    _cleanup_orphaned_webhook_node_auth(instance.webhook_trigger_id)


def _cleanup_orphaned_auth_if_unclaimed(
    trigger_id: int | None, kind: str, still_claimed: bool
) -> None:
    if trigger_id is None or still_claimed:
        return
    WebhookTriggerAuth.objects.filter(trigger_id=trigger_id, kind=kind).delete()


def _cleanup_orphaned_twilio_auth(trigger_id: int | None) -> None:
    _cleanup_orphaned_auth_if_unclaimed(
        trigger_id,
        WebhookTriggerAuthKind.TWILIO,
        still_claimed=TwilioChannel.objects.filter(
            webhook_trigger_id=trigger_id
        ).exists(),
    )


def _cleanup_orphaned_webhook_node_auth(trigger_id: int | None) -> None:
    _cleanup_orphaned_auth_if_unclaimed(
        trigger_id,
        WebhookTriggerAuthKind.WEBHOOK,
        still_claimed=WebhookTriggerNode.objects.filter(
            webhook_trigger_id=trigger_id
        ).exists(),
    )


@receiver(pre_save, sender=TwilioChannel)
def twilio_channel_pre_save_handler(sender, instance: TwilioChannel, **_):
    if instance.pk:
        instance._previous_webhook_trigger_id = (
            TwilioChannel.objects.filter(pk=instance.pk)
            .values_list("webhook_trigger_id", flat=True)
            .first()
        )
    else:
        instance._previous_webhook_trigger_id = None


@receiver(post_save, sender=TwilioChannel)
def twilio_channel_post_save_handler(sender, instance: TwilioChannel, **_):
    old_trigger_id = getattr(instance, "_previous_webhook_trigger_id", None)
    new_trigger_id = instance.webhook_trigger_id
    if old_trigger_id is not None and old_trigger_id != new_trigger_id:
        _cleanup_orphaned_twilio_auth(old_trigger_id)

    trigger = instance.webhook_trigger
    if trigger is None:
        return

    existing = getattr(trigger, "auth", None)
    if existing is not None and existing.kind != WebhookTriggerAuthKind.TWILIO:
        logger.error(
            f"Cannot sync Twilio auth onto trigger {trigger.pk}: its auth is "
            f"already configured for kind='{existing.kind}'."
        )
        return

    WebhookTriggerAuth.objects.update_or_create(
        trigger=trigger,
        defaults={
            "kind": WebhookTriggerAuthKind.TWILIO,
            "secret_id": instance.auth_token_secret_id,
        },
    )


@receiver(post_delete, sender=TwilioChannel)
def twilio_channel_post_delete_handler(sender, instance: TwilioChannel, **_):
    trigger_id = instance.webhook_trigger_id
    _cleanup_orphaned_twilio_auth(trigger_id)
