"""What a restore does besides bringing the batch back: free a taken or unproven
unique value before it, reconnect an outside service after it."""

import uuid

from tables.exceptions import RestoreNeedsTwilioAuthTokenError, TwilioUnavailableError
from tables.models import RealtimeChannel, TwilioChannel, WebhookTrigger
from tables.models.graph_models import TelegramTriggerNode
from tables.services.twilio_service import (
    PhoneNumberClaimRefusal,
    TwilioNoAnswerError,
    TwilioService,
)
from utils.logger import logger

_PHONE_NUMBER_UNVERIFIED_ON_RESTORE_MESSAGE = (
    "Could not verify the channel's phone number with Twilio. Try the restore again later."
)


def drop_unavailable_phone_number(channel: RealtimeChannel, batch: uuid.UUID) -> None:
    """Bring the channel back without its phone number unless the number is still its own.

    Follows the order of `TwilioService.claim_phone_number`: ownership is proven
    first, with the channel's own Twilio account, whether or not a live channel holds
    the number, so whether a restore asks Twilio says nothing about another
    organization's numbers. A number the account no longer has, or can't prove
    (credentials rejected, token deleted for good, malformed SID), is dropped, so a
    restore can't bring back a number nobody proved. Only a proven number is then
    checked against the live channels: one a live channel took meanwhile is dropped
    too, because a restore never takes a number from a live channel; only a save that
    proves ownership does. Runs inside the restore's transaction, so the Twilio call
    holds the binned channel's row lock: only a restore or purge of this same item
    waits on it.

    Raises:
        RestoreNeedsTwilioAuthTokenError: The auth token is linked but can't be read
            (binned, or not decryptable). A binned token restored first could still prove
            the number, so the number isn't dropped: the restore fails and the channel
            stays in the bin with it.
        TwilioUnavailableError: Twilio gave no answer. The restore fails and the channel
            stays in the bin with its number, so a later restore can still prove it.
    """
    binned = (
        TwilioChannel.all_objects.select_related("channel")
        .filter(channel_id=channel.pk, soft_delete_batch=batch)
        .first()
    )
    if binned is None or not binned.phone_number:
        return
    try:
        refusal = TwilioService().stored_number_refusal(binned)
    except TwilioNoAnswerError as error:
        raise TwilioUnavailableError(_PHONE_NUMBER_UNVERIFIED_ON_RESTORE_MESSAGE) from error
    if refusal is PhoneNumberClaimRefusal.AUTH_TOKEN_UNAVAILABLE:
        raise RestoreNeedsTwilioAuthTokenError()
    if refusal is not None:
        logger.info(
            "Restoring channel {channel_id} without its phone number: its Twilio account "
            "could not prove it ({refusal})",
            channel_id=channel.pk,
            refusal=refusal.value,
        )
    elif TwilioChannel.objects.filter(phone_number=binned.phone_number).exists():
        logger.info(
            "Restoring channel {channel_id} without its phone number: a live channel holds it",
            channel_id=channel.pk,
        )
    else:
        return
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
