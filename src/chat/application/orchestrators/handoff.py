from common.utils import utcnow
from domain.enums import Mode
from domain.models import Binding, Conversation

from application.orchestrators.events import Emitter


async def hand_off(
    emitter: Emitter, conversation: Conversation, binding: Binding, reason: str
) -> bool:
    """bot → awaiting_human when the binding allows it and the conversation is open. The caller
    saves the conversation."""
    if not binding.handoff_enabled or not conversation.is_open or conversation.mode != Mode.BOT:
        return False
    conversation.change_mode(Mode.AWAITING_HUMAN, utcnow())
    conversation.handoff_reason = reason
    conversation.late_reply_run_id = None
    await emitter.conversation(conversation, "mode.changed", {"mode": Mode.AWAITING_HUMAN.value})
    return True
