"""What a restore does besides bringing the batch back: free a taken unique value
before it, reconnect an outside service after it."""

import uuid

from tables.models import RealtimeChannel, TwilioChannel, WebhookTrigger
from tables.models.graph_models import TelegramTriggerNode


def drop_taken_phone_number(channel: RealtimeChannel, batch: uuid.UUID) -> None:
    """A phone number a live channel took meanwhile can't be renamed: the restored channel comes back without it."""
    binned = TwilioChannel.all_objects.filter(
        channel_id=channel.pk, soft_delete_batch=batch
    ).first()
    if binned is None or not binned.phone_number:
        return
    if TwilioChannel.objects.filter(phone_number=binned.phone_number).exists():
        TwilioChannel.all_objects.filter(pk=binned.pk).update(phone_number=None)


def register_telegram_bots(trigger: WebhookTrigger) -> None:
    """Register the Telegram bots of the trigger's live flows again.

    Their nodes kept the link while the trigger was binned, so the restore
    doesn't save them, and their post_save registration never runs. Its tunnel
    may also have come back on a new URL (an ngrok config without a domain).
    Runs after commit, after the tunnel configs' own re-registration.
    """
    from tables.services.telegram_trigger_service import TelegramTriggerService

    service = TelegramTriggerService()
    for node in TelegramTriggerNode.objects.filter(
        webhook_trigger_id=trigger.pk, graph__active=True
    ):
        service.register_and_log(node)
