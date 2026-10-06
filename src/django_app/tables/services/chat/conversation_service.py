import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum

from django.db import connection
from django.db.models import Q
from tables.exceptions import ChatBindingInactiveError, ChatOperatorMessageNotAllowedError
from tables.models import ChatBinding, ChatConversation, ChatMessage, Session
from tables.models.session_models import SessionTrigger
from tables.services.chat.channels import deliver
from tables.services.session_manager_service import SessionManagerService
from tables.services.trigger_spec import TriggerSpec

# First key of the two-key advisory lock form, so chat locks never meet other users of it.
_CHAT_LOCK_NAMESPACE = 0x43484154  # "CHAT"
_INT4_RANGE = 2**31

_RUNNING_STATUSES = (
    Session.SessionStatus.PENDING,
    Session.SessionStatus.RUN,
    Session.SessionStatus.WAIT_FOR_USER,
)


class ChatAction(StrEnum):
    FORWARDED_TO_OPERATOR = "forwarded_to_operator"
    BUDGET_EXHAUSTED = "budget_exhausted"
    STARTED = "started"
    INTERRUPTED_AND_RESTARTED = "interrupted_and_restarted"
    QUEUED = "queued"


@dataclass(frozen=True)
class SubmitResult:
    conversation: ChatConversation
    message: ChatMessage
    action: ChatAction


@contextmanager
def _conversation_lock(conversation_id: int) -> Iterator[None]:
    """Serialize every decision on one conversation, across web and redis-listener processes.

    A session-level advisory lock rather than `select_for_update`: `run_session` must
    commit the Session row before it publishes to crew, and a row lock lives only as long
    as an open transaction. Inside one, crew's first status updates would reference a
    session other processes cannot see yet.
    """
    # Two distinct conversations sharing a key only serialize each other, which is harmless.
    lock_keys = [_CHAT_LOCK_NAMESPACE, conversation_id % _INT4_RANGE]
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_lock(%s, %s)", lock_keys)
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s, %s)", lock_keys)


def conversation_tokens_used(conversation: ChatConversation) -> int:
    """Total tokens of every run of the conversation. Uses prefetched `sessions` if present."""
    # PROTO: Session.token_usage is written by the session-status listener, which can lag
    # the graph_end message by a few ms, so the run that just ended may not be counted yet.
    return sum(
        (session.token_usage or {}).get("total_tokens", 0)
        for session in conversation.sessions.all()
    )


def parse_end_node_result(end_node_result) -> tuple[str, bool, str]:
    """Read a flow's end node result as (reply, handoff, handoff_reason).

    A dict with "reply" and/or "handoff" is the chat contract; a plain string is the reply;
    anything else non-empty is sent as its JSON dump.
    """
    if isinstance(end_node_result, str):
        return end_node_result, False, ""
    if isinstance(end_node_result, dict) and (
        "reply" in end_node_result or "handoff" in end_node_result
    ):
        return (
            str(end_node_result.get("reply") or ""),
            bool(end_node_result.get("handoff")),
            str(end_node_result.get("handoff_reason") or "flow requested handoff"),
        )
    if not end_node_result:
        return "", False, ""
    return json.dumps(end_node_result, ensure_ascii=False, default=str), False, ""


class ConversationService:
    """Routes end-user messages to flow runs and run results back to end users.

    The flow knows nothing about chat: it receives the conversation as input variables and
    returns its reply through the end node. This service owns history, concurrency
    (interrupt / queue), the per-conversation token budget and human handoff.

    Every public method that changes a conversation holds `_conversation_lock` for the
    whole decision. Private helpers change the conversation object only in memory (messages
    and the `sessions` M2M are written at once); the public method saves it once, before
    releasing the lock.
    """

    def __init__(self) -> None:
        self.session_manager_service = SessionManagerService()

    # ----- inbound -----

    def submit_user_message(
        self, binding: ChatBinding, external_id: str, content: str
    ) -> SubmitResult:
        """Store an end-user message and decide what happens with it.

        May stop a running session (interrupt policy) and start a new one.

        Raises:
            ChatBindingInactiveError: The binding is switched off.
        """
        if not binding.is_active:
            raise ChatBindingInactiveError()
        conversation, _ = ChatConversation.objects.get_or_create(
            binding=binding, external_id=external_id
        )
        with _conversation_lock(conversation.pk):
            conversation.refresh_from_db()
            message = self._store_message(conversation, ChatMessage.Role.USER, content)
            action = self._route_user_message(conversation)
            conversation.save()
        return SubmitResult(conversation=conversation, message=message, action=action)

    def submit_telegram_update(self, graph_id: int, payload: dict) -> bool:
        """Route a Telegram update to the graph's active telegram chat binding.

        Returns:
            True when the graph has such a binding (the update is the chat layer's,
            whether or not it carried text); False when the caller should run the
            graph the plain trigger way.
        """
        binding = ChatBinding.objects.filter(
            graph_id=graph_id, channel=ChatBinding.Channel.TELEGRAM, is_active=True
        ).first()
        if binding is None:
            return False
        message = (payload or {}).get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        text = message.get("text")
        # PROTO: non-text updates (photos, voice, inline-keyboard callbacks) are dropped.
        if chat_id is None or not text:
            return True
        self.submit_user_message(binding, str(chat_id), text)
        return True

    def _route_user_message(self, conversation: ChatConversation) -> ChatAction:
        if conversation.mode in (ChatConversation.Mode.HUMAN, ChatConversation.Mode.AWAITING_HUMAN):
            return ChatAction.FORWARDED_TO_OPERATOR
        if conversation.mode == ChatConversation.Mode.CLOSED:
            conversation.mode = ChatConversation.Mode.BOT
        if self._is_budget_exhausted(conversation):
            self._handle_budget_exhausted(conversation)
            return ChatAction.BUDGET_EXHAUSTED
        if not self._is_running(conversation):
            self._start_run(conversation)
            return ChatAction.STARTED
        if conversation.binding.concurrency_policy == ChatBinding.ConcurrencyPolicy.QUEUE:
            # Picked up by on_session_finished when the active run ends.
            return ChatAction.QUEUED
        self._interrupt_active_run(conversation)
        self._start_run(conversation)
        return ChatAction.INTERRUPTED_AND_RESTARTED

    # ----- run results -----

    def on_session_finished(
        self, session_id: int, status: str, end_node_result: dict | str | None = None
    ) -> None:
        """Apply a finished run to its conversation; a no-op for sessions not started by chat.

        Only the conversation's active session is accepted. A superseded run (replaced by an
        interrupt) that still reached END has its reply stored as `interrupted` and is never
        delivered. When the run leaves the conversation in bot mode with unanswered user
        messages (queue policy), the next run starts here.

        Args:
            status: A terminal `Session.SessionStatus` (end, error, stop, expired).
            end_node_result: The `graph_end` message's result; only meaningful for END.
        """
        conversation_id = self._conversation_id_for_session(session_id)
        if conversation_id is None:
            return
        with _conversation_lock(conversation_id):
            conversation = ChatConversation.objects.select_related("binding").get(
                pk=conversation_id
            )
            if conversation.active_session_id != session_id:
                if status == Session.SessionStatus.END:
                    self._store_superseded_reply(conversation, session_id, end_node_result)
                return

            conversation.active_session = None
            if status == Session.SessionStatus.END:
                self._accept_result(conversation, session_id, end_node_result)
            elif status == Session.SessionStatus.STOP:
                self._on_active_run_stopped(conversation, session_id)
            else:
                self._store_message(
                    conversation,
                    ChatMessage.Role.SYSTEM,
                    f"The flow run ended with status '{status}'.",
                    session_id=session_id,
                )
                if conversation.binding.handoff_enabled:
                    self._hand_off(conversation, "flow error")

            if conversation.mode == ChatConversation.Mode.BOT:
                self._continue_with_pending(conversation)
            conversation.save()

    @staticmethod
    def _conversation_id_for_session(session_id: int) -> int | None:
        # The trigger row is committed together with the session, before crew sees it, so
        # this lookup cannot miss a run whose start is still holding the conversation lock.
        extra = (
            SessionTrigger.objects.filter(
                session_id=session_id, trigger_type=SessionTrigger.TriggerType.CHAT
            )
            .values_list("extra", flat=True)
            .first()
        )
        return (extra or {}).get("conversation_id")

    def _accept_result(
        self, conversation: ChatConversation, session_id: int, end_node_result
    ) -> None:
        reply, handoff, handoff_reason = parse_end_node_result(end_node_result)
        if reply:
            message = self._store_message(
                conversation, ChatMessage.Role.ASSISTANT, reply, session_id=session_id
            )
            # PROTO: delivered while holding the lock; the real version uses an outbox.
            deliver(conversation, message)
        if handoff and conversation.binding.handoff_enabled:
            self._hand_off(conversation, handoff_reason)

    def _store_superseded_reply(
        self, conversation: ChatConversation, session_id: int, end_node_result
    ) -> None:
        reply, _, _ = parse_end_node_result(end_node_result)
        if reply:
            ChatMessage.objects.create(
                conversation=conversation,
                role=ChatMessage.Role.ASSISTANT,
                content=reply,
                session_id=session_id,
                interrupted=True,
            )

    def _on_active_run_stopped(self, conversation: ChatConversation, session_id: int) -> None:
        # Interrupts replace active_session before stopping, so this is a stop from outside
        # the chat layer: the crew token-budget guard, a timeout, or a manual stop in the UI.
        if self._is_budget_exhausted(conversation):
            self._handle_budget_exhausted(conversation)
            return
        self._store_message(
            conversation,
            ChatMessage.Role.SYSTEM,
            "The flow run was stopped.",
            session_id=session_id,
        )

    def _continue_with_pending(self, conversation: ChatConversation) -> None:
        if not self._pending_user_messages(conversation):
            return
        if self._is_budget_exhausted(conversation):
            self._handle_budget_exhausted(conversation)
            return
        self._start_run(conversation)

    # ----- operator actions -----

    def claim(self, conversation: ChatConversation, operator) -> ChatConversation:
        """Hand the conversation to `operator`. A bot run in flight is stopped, its reply dropped."""
        with _conversation_lock(conversation.pk):
            conversation.refresh_from_db()
            self._stop_active_run(conversation)
            conversation.mode = ChatConversation.Mode.HUMAN
            # PROTO: claiming over another operator is allowed; the real version asks first.
            conversation.assigned_operator = operator
            conversation.save()
        return conversation

    def release(self, conversation: ChatConversation) -> ChatConversation:
        """Give the conversation back to the bot; the next user message starts a run."""
        with _conversation_lock(conversation.pk):
            conversation.refresh_from_db()
            conversation.mode = ChatConversation.Mode.BOT
            conversation.assigned_operator = None
            conversation.handoff_reason = ""
            conversation.save()
        return conversation

    def close(self, conversation: ChatConversation) -> ChatConversation:
        """Close the conversation; the next user message reopens it in bot mode."""
        with _conversation_lock(conversation.pk):
            conversation.refresh_from_db()
            self._stop_active_run(conversation)
            conversation.mode = ChatConversation.Mode.CLOSED
            conversation.assigned_operator = None
            conversation.save()
        return conversation

    def send_operator_message(
        self, conversation: ChatConversation, operator, content: str
    ) -> ChatMessage:
        """Store an operator reply and deliver it to the end user.

        Raises:
            ChatOperatorMessageNotAllowedError: Not in human mode, or `operator` has not
                claimed the conversation.
        """
        with _conversation_lock(conversation.pk):
            conversation.refresh_from_db()
            if (
                conversation.mode != ChatConversation.Mode.HUMAN
                or conversation.assigned_operator_id != operator.pk
            ):
                raise ChatOperatorMessageNotAllowedError()
            message = self._store_message(
                conversation, ChatMessage.Role.OPERATOR, content, author=operator
            )
            conversation.save()
            deliver(conversation, message)
        return message

    # ----- runs -----

    def _is_running(self, conversation: ChatConversation) -> bool:
        # The status check, not just the FK, guards against a missed terminal event:
        # a dead active session must not block the conversation forever.
        return (
            conversation.active_session_id is not None
            and conversation.active_session.status in _RUNNING_STATUSES
        )

    def _start_run(self, conversation: ChatConversation) -> None:
        binding = conversation.binding
        pending = self._pending_user_messages(conversation)
        history = self._history(conversation, exclude_ids=[message.pk for message in pending])
        new_messages = [message.content for message in pending]
        variables = {
            "conversation": {
                "id": conversation.pk,
                "channel": binding.channel,
                "external_id": conversation.external_id,
                "history": history,
                "new_messages": new_messages,
            },
            # Same keys the existing EpicChat flows read.
            "context": {"chat_history": history, "user_input": "\n".join(new_messages)},
        }
        session_id = self.session_manager_service.run_session(
            graph_id=binding.graph_id,
            variables=variables,
            trigger=TriggerSpec.chat(conversation_id=conversation.pk, binding_id=binding.pk),
            token_budget=self._remaining_budget(conversation),
        )
        ChatMessage.objects.filter(pk__in=[message.pk for message in pending]).update(
            session_id=session_id
        )
        conversation.active_session_id = session_id
        conversation.sessions.add(session_id)

    def _interrupt_active_run(self, conversation: ChatConversation) -> None:
        stopped_session_id = conversation.active_session_id
        self._stop_active_run(conversation)
        # The stopped run will never answer what it consumed: hand it to the next run.
        conversation.messages.filter(
            role=ChatMessage.Role.USER, session_id=stopped_session_id
        ).update(session=None)

    def _stop_active_run(self, conversation: ChatConversation) -> None:
        if self._is_running(conversation):
            self.session_manager_service.stop_session(conversation.active_session_id)
        conversation.active_session = None

    @staticmethod
    def _pending_user_messages(conversation: ChatConversation) -> list[ChatMessage]:
        """User messages no run has consumed yet and no non-run answer has covered.

        Not "user messages after the last assistant message": with the queue policy the
        first run's reply is stored after the queued messages and would hide them. A reply
        that is not a run's (operator message, budget-exhausted reply) does cover
        everything before it.
        """
        cutoff_id = (
            conversation.messages.filter(
                Q(role=ChatMessage.Role.OPERATOR)
                | Q(role=ChatMessage.Role.ASSISTANT, session__isnull=True)
            )
            .order_by("-id")
            .values_list("id", flat=True)
            .first()
        ) or 0
        return list(
            conversation.messages.filter(
                role=ChatMessage.Role.USER, session__isnull=True, id__gt=cutoff_id
            ).order_by("id")
        )

    @staticmethod
    def _history(conversation: ChatConversation, exclude_ids: list[int]) -> list[dict]:
        # The last N messages other than the new ones, not "N before the first new one":
        # with the queue policy the previous run's reply comes after the first queued message.
        window = conversation.binding.history_window
        if window == 0:
            return []
        messages = (
            conversation.messages.filter(
                role__in=[
                    ChatMessage.Role.USER,
                    ChatMessage.Role.ASSISTANT,
                    ChatMessage.Role.OPERATOR,
                ],
                interrupted=False,
            )
            .exclude(pk__in=exclude_ids)
            .order_by("-id")[:window]
        )
        return [
            {"role": message.role, "content": message.content} for message in reversed(messages)
        ]

    # ----- budget and handoff -----

    def _remaining_budget(self, conversation: ChatConversation) -> int | None:
        budget = conversation.binding.token_budget_per_conversation
        if budget is None:
            return None
        return budget - conversation_tokens_used(conversation)

    def _is_budget_exhausted(self, conversation: ChatConversation) -> bool:
        remaining = self._remaining_budget(conversation)
        return remaining is not None and remaining <= 0

    def _handle_budget_exhausted(self, conversation: ChatConversation) -> None:
        binding = conversation.binding
        if binding.on_budget_exhausted == ChatBinding.OnBudgetExhausted.HANDOFF:
            self._hand_off(conversation, "budget")
            return
        message = self._store_message(
            conversation,
            ChatMessage.Role.ASSISTANT,
            binding.budget_exhausted_message or "This conversation has reached its usage limit.",
        )
        deliver(conversation, message)

    @staticmethod
    def _hand_off(conversation: ChatConversation, reason: str) -> None:
        conversation.mode = ChatConversation.Mode.AWAITING_HUMAN
        conversation.handoff_reason = reason

    @staticmethod
    def _store_message(
        conversation: ChatConversation,
        role: str,
        content: str,
        *,
        session_id: int | None = None,
        author=None,
    ) -> ChatMessage:
        message = ChatMessage.objects.create(
            conversation=conversation,
            role=role,
            content=content,
            session_id=session_id,
            author=author,
        )
        conversation.last_message_at = message.created_at
        return message
