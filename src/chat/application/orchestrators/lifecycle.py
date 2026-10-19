from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from domain.enums import CloseReason, Mode, OnResponseTimeout, Role, RunState
from domain.errors import UpstreamUnavailableError
from domain.models import Conversation
from loguru import logger

from application.orchestrators.events import Emitter, store_message
from application.ports import AbstractFanout, AbstractFlowRunner, AbstractUnitOfWork


async def free_run_slot(
    uow: AbstractUnitOfWork, conversation: Conversation
) -> tuple[bool, int | None]:
    """Take the run slot from a run in flight; the caller saves the conversation.

    The run is not stopped here, so its late callback still finds the receipt and only counts
    its tokens. Stop it after commit with `stop_session`.

    Returns:
        Whether a run was in flight, and its session to stop. No session while its start is
        unanswered: a submit still waiting for Django stops the run itself, and after a timeout
        the run cannot be named.
    """
    run_in_flight = conversation.run_state != RunState.IDLE
    receipt = (
        await uow.receipts.get(conversation.active_run_id)
        if run_in_flight and conversation.active_run_id
        else None
    )
    conversation.run_state, conversation.active_run_id, conversation.active_since = (
        RunState.IDLE,
        None,
        None,
    )
    return run_in_flight, receipt.session_id if receipt else None


async def close_conversation(
    uow: AbstractUnitOfWork,
    emitter: Emitter,
    conversation: Conversation,
    reason: CloseReason,
    now: datetime,
    by_user_id: int | None = None,
) -> tuple[dict, int | None]:
    """Close an open conversation and tell both streams; the caller saves and commits.

    A run in flight loses its slot and finishes as `stop` on the visitor's stream. Then
    `conversation.closed` goes to both streams, the visitor's without operator ids, and
    `conversation.updated` to the inbox. The run is not stopped here: call `stop_session`
    after commit.

    Returns:
        The conversation's inbox row, as `conversation.updated` carried it, and the session to stop.
    """
    run_in_flight, session_to_stop = await free_run_slot(uow, conversation)
    conversation.close(reason, now, by_user_id)
    if run_in_flight:
        await emitter.conversation(conversation, "run.finished", {"status": "stop"})
    await emitter.conversation_closed(conversation)
    row = await emitter.conversation_updated(conversation)
    return row, session_to_stop


async def stop_session(flows: AbstractFlowRunner, session_id: int | None) -> None:
    """Ask Django to stop a run that lost its slot; best effort, None does nothing.

    A run Django could not be told about goes on, and its callback still counts its tokens.
    """
    if session_id is None:
        return
    try:
        await flows.stop_run(session_id)
    except UpstreamUnavailableError as error:
        logger.warning("Could not stop session {} after it lost its slot: {}", session_id, error)


class LifecycleTimers:
    """Each desk's inactivity rules, applied one conversation at a time by the reconcile loop.

    Every worker runs the loop, so two may pick the same conversation. Each item locks its row
    with SKIP LOCKED, in a transaction of its own, and re-checks the rule under the lock: a row
    another transaction holds is skipped (a later pass gets it), and one that changed since it
    was picked is left alone.
    """

    def __init__(self, uow_factory: Callable[[], AbstractUnitOfWork], *, fanout: AbstractFanout):
        self._uow = uow_factory
        self._fanout = fanout

    async def hand_back(self, conversation_id: UUID, now: datetime) -> bool:
        """Hand a visitor who waited past the desk's response time back to the bot.

        The visitor's stream gets `mode.changed`, then the desk's notice as the bot's message
        (an empty notice posts none); the holder, if any, lets go.

        Returns:
            False when the row is locked, gone, or no longer due on a hand-back desk.
        """
        async with self._uow() as uow:
            conversation = await uow.conversations.get(
                conversation_id, for_update=True, skip_locked=True
            )
            if conversation is None:
                return False
            binding = await uow.bindings.get(conversation.binding_id)
            due = binding.response_due_at(conversation)
            if binding.on_response_timeout != OnResponseTimeout.HANDBACK or due is None:
                return False
            if now <= due:
                return False
            emitter = Emitter(uow, self._fanout)
            conversation.return_to_bot(now)
            await emitter.conversation(conversation, "mode.changed", {"mode": Mode.BOT.value})
            if binding.handback_message.strip():
                await store_message(
                    uow, emitter, conversation, Role.ASSISTANT, binding.handback_message
                )
            await emitter.conversation_updated(conversation)
            await uow.conversations.update(conversation)
            await uow.commit()
            await emitter.flush()
        return True

    async def close_inactive(self, conversation_id: UUID, now: datetime) -> bool:
        """Close a Support conversation silent past the desk's close-after time (reason `inactive`).

        Returns:
            False when the row is locked, gone, or no longer due.
        """
        async with self._uow() as uow:
            conversation = await uow.conversations.get(
                conversation_id, for_update=True, skip_locked=True
            )
            if conversation is None:
                return False
            binding = await uow.bindings.get(conversation.binding_id)
            due = binding.idle_close_at(conversation)
            if due is None or now <= due:
                return False
            emitter = Emitter(uow, self._fanout)
            # No run in flight (`idle_close_at` asks for none), so there is no session to stop.
            await close_conversation(uow, emitter, conversation, CloseReason.INACTIVE, now)
            await uow.conversations.update(conversation)
            await uow.commit()
            await emitter.flush()
        return True
