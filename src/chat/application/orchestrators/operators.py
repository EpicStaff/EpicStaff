from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from common.utils import utcnow
from domain.enums import CloseReason, InboxOrder, InboxSection, Mode, Role
from domain.errors import ClaimedByOtherError, NotAssignedError, NotFoundError
from domain.models import Conversation, InboxBadge, Message
from domain.search import InboxSearch

from application.orchestrators.events import Emitter, conversation_summary, store_message
from application.orchestrators.lifecycle import close_conversation, free_run_slot, stop_session
from application.ports import AbstractFanout, AbstractFlowRunner, AbstractUnitOfWork


class OperatorOrchestrator:
    """The inbox side: everything here is scoped by the operator's org."""

    def __init__(
        self,
        uow_factory: Callable[[], AbstractUnitOfWork],
        *,
        flows: AbstractFlowRunner,
        fanout: AbstractFanout,
    ):
        self._uow = uow_factory
        self._flows = flows
        self._fanout = fanout

    async def list_conversations(
        self,
        org_id: int,
        binding_id: UUID | None,
        section: InboxSection,
        after: tuple[datetime, UUID] | None,
        page_size: int,
        mode: Mode | None = None,
        *,
        order: InboxOrder = InboxOrder.NEWEST,
        holder_id: int | None = None,
        search: InboxSearch | None = None,
    ) -> tuple[list[dict], tuple[datetime, UUID] | None]:
        """One page of an inbox section and the keyset `(at, id)` that continues it.

        `at` is the section's `key_field`. Test conversations are listed only in the test
        section, whatever their state, closed ones included.

        Args:
            after: Key returned with the previous page of the same section and order. Untrusted
                client input: it only positions the page, `org_id` always scopes it.
            mode: Only rows in this mode, in the same order; the caller keeps it to the
                human section's modes.
            order: Newest or oldest activity first; Waiting and Human are queues and ignore it,
                and Closed always lists the most recently closed first.
            holder_id: Only conversations this operator holds (Mine). The caller passes the
                verified operator, never a client-supplied id.
            search: Only conversations it matches.

        Returns:
            The rows as `conversation_summary` builds them, and the last row's key; the key is
            None on the last page.
        """
        async with self._uow() as uow:
            # One extra row tells whether a next page exists without a COUNT.
            rows = await uow.conversations.list(
                org_id,
                binding_id,
                section,
                limit=page_size + 1,
                after=after,
                mode=mode,
                order=order,
                holder_id=holder_id,
                search=search,
            )
            page = rows[:page_size]
            names = await uow.operator_profiles.names(
                org_id, {user_id for conversation in page for user_id in conversation.operator_ids}
            )
        summaries = [conversation_summary(conversation, names) for conversation in page]
        if len(rows) <= page_size:
            return summaries, None
        last = page[-1]
        return summaries, (getattr(last, section.key_field), last.id)

    async def badges(self, org_id: int) -> list[InboxBadge]:
        """What the Waiting counts are made of, org-wide, tests and closed conversations excluded.

        Each row names its desk and holder, so one answer gives the counts per desk, for all
        desks and for Mine.
        """
        async with self._uow() as uow:
            return await uow.conversations.badges(org_id)

    async def get(self, conversation_id: UUID, org_id: int) -> dict:
        """One conversation's inbox row, whichever section it is in, open or closed.

        Raises:
            NotFoundError: No such conversation in `org_id`.
        """
        async with self._uow() as uow:
            conversation = await uow.conversations.get(conversation_id, org_id=org_id)
            if conversation is None:
                raise NotFoundError()
            names = await uow.operator_profiles.names(org_id, conversation.operator_ids)
        return conversation_summary(conversation, names)

    async def messages(
        self, conversation_id: UUID, org_id: int, before: UUID | None, limit: int
    ) -> tuple[list[Message], dict[int, str]]:
        """A page of the conversation's messages, and the display names of the operators who wrote them."""
        async with self._uow() as uow:
            if await uow.conversations.get(conversation_id, org_id=org_id) is None:
                raise NotFoundError()
            page = await uow.messages.page(conversation_id, before, limit)
            names = await uow.operator_profiles.names(
                org_id, {message.author_user_id for message in page} - {None}
            )
        return page, names

    async def claim(
        self,
        conversation_id: UUID,
        org_id: int,
        operator_id: int,
        force: bool,
        *,
        display_name: str | None,
    ) -> dict:
        """Mode `human`, operator = caller; a run in flight is stopped, its late callback counts tokens only.

        Args:
            display_name: The caller's EpicStaff name, remembered for the inbox when it changed.

        Returns:
            The conversation's inbox row, as `conversation.updated` carried it.

        Raises:
            ConversationClosedError: It is closed.
        """
        async with self._uow() as uow:
            conversation = await uow.conversations.get(
                conversation_id, org_id=org_id, for_update=True
            )
            if conversation is None:
                raise NotFoundError()
            conversation.ensure_open()
            if _held_by_another(conversation, operator_id) and not force:
                raise ClaimedByOtherError()
            run_in_flight, session_to_stop = await free_run_slot(uow, conversation)
            now = utcnow()
            await uow.operator_profiles.remember(org_id, operator_id, display_name, now)
            conversation.change_mode(Mode.HUMAN, now)
            conversation.assigned_operator_id = operator_id
            conversation.late_reply_run_id = None
            emitter = Emitter(uow, self._fanout)
            await emitter.conversation(conversation, "mode.changed", {"mode": Mode.HUMAN.value})
            if run_in_flight:
                await emitter.conversation(conversation, "run.finished", {"status": "stop"})
            row = await emitter.conversation_updated(conversation)
            await uow.conversations.update(conversation)
            await uow.commit()
            await emitter.flush()
        # The claim stands if Django cannot be told: the run goes on and only counts its tokens.
        await stop_session(self._flows, session_to_stop)
        return row

    async def close(
        self,
        conversation_id: UUID,
        org_id: int,
        operator_id: int,
        force: bool,
        *,
        display_name: str | None,
    ) -> dict:
        """Close the conversation for good (reason `resolved`), as the caller.

        The UI calls it Resolve on Support desks and Close conversation on Ongoing ones; both
        end the thread, and the visitor's next message starts a new conversation. Idempotent: a
        conversation already closed, for any reason, is answered as it is. A run in flight is
        stopped; its late callback only counts tokens. No message is posted.

        Args:
            force: Close one another operator holds.
            display_name: The caller's EpicStaff name, remembered for the inbox when it changed.

        Returns:
            The conversation's inbox row, as `conversation.updated` carried it.

        Raises:
            NotFoundError: No such conversation in `org_id`.
            ClaimedByOtherError: Another operator holds it and `force` is false.
        """
        async with self._uow() as uow:
            conversation = await uow.conversations.get(
                conversation_id, org_id=org_id, for_update=True
            )
            if conversation is None:
                raise NotFoundError()
            if not conversation.is_open:
                names = await uow.operator_profiles.names(org_id, conversation.operator_ids)
                return conversation_summary(conversation, names)
            if _held_by_another(conversation, operator_id) and not force:
                raise ClaimedByOtherError()
            now = utcnow()
            await uow.operator_profiles.remember(org_id, operator_id, display_name, now)
            emitter = Emitter(uow, self._fanout)
            row, session_to_stop = await close_conversation(
                uow, emitter, conversation, CloseReason.RESOLVED, now, by_user_id=operator_id
            )
            await uow.conversations.update(conversation)
            await uow.commit()
            await emitter.flush()
        await stop_session(self._flows, session_to_stop)
        return row

    async def release(self, conversation_id: UUID, org_id: int, operator_id: int) -> dict:
        """Back to the bot; a conversation already there is left as it is.

        Returns:
            The conversation's inbox row, as `conversation.updated` carried it.

        Raises:
            ConversationClosedError: It is closed, whatever its mode.
        """
        async with self._uow() as uow:
            conversation = await uow.conversations.get(
                conversation_id, org_id=org_id, for_update=True
            )
            if conversation is None:
                raise NotFoundError()
            conversation.ensure_open()
            if conversation.mode == Mode.BOT:
                names = await uow.operator_profiles.names(org_id, conversation.operator_ids)
                return conversation_summary(conversation, names)
            conversation.return_to_bot(utcnow())
            emitter = Emitter(uow, self._fanout)
            await emitter.conversation(conversation, "mode.changed", {"mode": Mode.BOT.value})
            row = await emitter.conversation_updated(conversation)
            await uow.conversations.update(conversation)
            await uow.commit()
            await emitter.flush()
        return row

    async def reply(
        self,
        conversation_id: UUID,
        org_id: int,
        operator_id: int,
        content: str,
        *,
        display_name: str | None,
    ) -> tuple[Message, str | None]:
        """Post the caller's reply to the visitor; it ends the visitor's wait.

        Visitors see it under the caller's alias on the desk, else the desk's operator name.

        Args:
            display_name: The caller's EpicStaff name, remembered for the inbox when it changed.

        Returns:
            The stored message and its author's name on record (None when none ever was).

        Raises:
            ConversationClosedError: It is closed.
        """
        async with self._uow() as uow:
            conversation = await uow.conversations.get(
                conversation_id, org_id=org_id, for_update=True
            )
            if conversation is None:
                raise NotFoundError()
            conversation.ensure_open()
            if conversation.mode != Mode.HUMAN or conversation.assigned_operator_id != operator_id:
                raise NotAssignedError()
            author_name = await uow.operator_profiles.remember(
                org_id, operator_id, display_name, utcnow()
            )
            # What visitors see, fixed on the message now: a later alias or desk rename leaves it.
            binding, alias = await uow.bindings.get_with_operator_alias(
                conversation.binding_id, operator_id
            )
            emitter = Emitter(uow, self._fanout)
            message = await store_message(
                uow,
                emitter,
                conversation,
                Role.OPERATOR,
                content,
                author_user_id=operator_id,
                author_name=author_name,
                visible_name=binding.operator_visible_name(alias),
            )
            await emitter.conversation_updated(conversation)
            await uow.conversations.update(conversation)
            await uow.commit()
            await emitter.flush()
        return message, author_name


def _held_by_another(conversation: Conversation, operator_id: int) -> bool:
    """Another operator holds it: claiming or closing it then takes `force` (409 claimed_by_other)."""
    return conversation.mode == Mode.HUMAN and conversation.assigned_operator_id not in (
        None,
        operator_id,
    )
