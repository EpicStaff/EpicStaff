from tables.exceptions import TelegramApiError
from tables.models import ChatBinding, ChatConversation, ChatMessage, TelegramTriggerNode
from tables.services.secrets import SecretResolutionError, secret_resolver
from tables.services.telegram_trigger_service import TelegramTriggerService
from utils.logger import logger


def deliver(conversation: ChatConversation, message: ChatMessage) -> None:
    """Send a stored outbound message to the end user over the binding's channel.

    A failed delivery is logged, not raised: the message is already stored and the
    caller (a run finishing, an operator reply) must not be rolled back by a send error.
    """
    channel = conversation.binding.channel
    if channel == ChatBinding.Channel.WIDGET:
        # PROTO: widget clients poll the messages endpoint; the real version pushes via SSE.
        return
    if channel == ChatBinding.Channel.TELEGRAM:
        _deliver_telegram(conversation, message)


def _deliver_telegram(conversation: ChatConversation, message: ChatMessage) -> None:
    binding = conversation.binding
    # PROTO: uses the first telegram trigger node of the graph; the real version stores
    # the bot (secret) on the binding itself.
    node = TelegramTriggerNode.objects.filter(graph_id=binding.graph_id).first()
    if node is None or node.telegram_bot_api_key_secret_id is None:
        logger.warning(
            "Chat binding {} has no telegram bot configured; message {} not delivered",
            binding.pk,
            message.pk,
        )
        return
    try:
        bot_api_key = secret_resolver.resolve(
            secret_id=node.telegram_bot_api_key_secret_id,
            org_id=binding.org_id,
            context="ChatBinding telegram delivery",
        )
        TelegramTriggerService().send_message(
            telegram_bot_api_key=bot_api_key,
            chat_id=conversation.external_id,
            text=message.content,
        )
    except (TelegramApiError, SecretResolutionError) as error:
        # Both errors are built without the bot token, so their text is safe to log.
        logger.error("Telegram delivery of chat message {} failed: {}", message.pk, str(error))
